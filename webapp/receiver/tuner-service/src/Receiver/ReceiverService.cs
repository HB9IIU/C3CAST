using opentuner;
using opentuner.MediaSources.Minitiouner.HardwareInterfaces;
using Serilog;
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;
using System.Threading;

namespace QocastPlayer.Receiver
{
    public enum ReceiverState
    {
        Disconnected,   // tuner not found / unplugged
        Waiting,        // tuner ready, no frequency from QOCAST yet
        Tuning,         // tuned, no signal locked
        Locked          // signal locked, stream flowing
    }

    // The tuner chosen in player.json: opens it, retries every 5 s while it is missing,
    // tunes it, and copies the received stream into Stream while the signal is locked.
    // Replaces OpenTuner's MinitiounerSource without its panels, recorders and streamers.
    public sealed class ReceiverService : IDisposable
    {
        public const uint MinIfKhz = 144000;
        public const uint MaxIfKhz = 2450000;
        private const int RetryMs = 5000;
        private const int ThreadStopMs = 3000;

        private readonly PlayerConfig _config;
        private readonly object _lock = new object();
        private readonly ManualResetEvent _stopEvent = new ManualResetEvent(false);
        private Thread _supervisor;

        // the session currently owning the tuner (null while disconnected)
        private Session _session;

        // last accepted request, re-applied after the tuner is plugged in again
        private TuneRequest _lastRequest;

        private ReceiverState _state = ReceiverState.Disconnected;
        private TunerStatus _lastStatus;

        // station name etc. from the stream (OpenTuner's TSParserThread, fed while locked)
        private readonly TSParserThread _parser;
        private TSStatus _service;

        // received transport stream, read by the video player; oldest bytes are dropped when full
        public CircularBuffer Stream { get; } = new CircularBuffer(GlobalDefines.CircularBufferStartingCapacity);

        // raised on a worker thread
        public event Action<ReceiverState> StateChanged;

        public ReceiverService(PlayerConfig config)
        {
            _config = config;
            _parser = new TSParserThread(OnService);
        }

        public string HardwareName { get; private set; }

        // loopback UDP port the locked stream is sent to, 0 = not sent
        public int TsUdpPort { get; set; }

        public ReceiverState State
        {
            get { lock (_lock) return _state; }
        }

        public TuneRequest LastRequest
        {
            get { lock (_lock) return _lastRequest; }
        }

        public TunerStatus LastStatus
        {
            get { lock (_lock) return _lastStatus; }
        }

        public bool Connected
        {
            get { lock (_lock) return _session != null; }
        }

        // ---- second channel: only a PicoTuner has one (two demodulators, two streams) ----
        // The Player stays the only owner of the USB device: channel 2's stream goes out by UDP on this
        // computer, to a second player window (Player 2) that tunes it through the same API ("tuner": 2).

        public int Tuner2UdpPort { get; set; } = 5002;

        private TuneRequest _lastRequest2;

        public TuneRequest LastRequest2
        {
            get { lock (_lock) return _lastRequest2; }
        }

        public bool SecondChannel
        {
            get { lock (_lock) return _session != null && _session.IsPico; }
        }

        public bool Tuner2Locked
        {
            get { lock (_lock) return _session != null && _session.Locked2; }
        }

        public void Tune2(long rfKhz, long symbolRateKsps, bool direct = false)
        {
            string error = CheckTune(rfKhz, symbolRateKsps, direct);
            if (error != null)
                throw new ArgumentOutOfRangeException(nameof(rfKhz), error);

            long ifKhz = direct ? rfKhz : rfKhz - _config.lnb_offset_khz;
            var request = new TuneRequest(rfKhz, (uint)ifKhz, (uint)symbolRateKsps, direct);
            Session session;
            lock (_lock)
            {
                _lastRequest2 = request;
                session = _session;
            }

            Log.Information("Tune channel 2: {Rf} kHz (IF {If} kHz), {Sr} kS/s", rfKhz, ifKhz, symbolRateKsps);
            if (session != null && session.IsPico)
                session.Tune2(request);
        }

        private void OnService(TSStatus status)
        {
            TSStatus previous;
            lock (_lock)
            {
                previous = _service;
                _service = status;
            }
            if (previous == null || previous.ServiceName != status.ServiceName)
                Log.Information("Receiver: station {Name} ({Provider})", status.ServiceName, status.ServiceProvider);
        }

        // service name / provider of the locked station, null until known
        public TSStatus Service
        {
            get { lock (_lock) return _service; }
        }

        public void Start()
        {
            // runs for the whole player life (it has no stop of its own), never cleared:
            // clearing it while it waits inside a packet would make it spin
            new Thread(_parser.worker_thread) { Name = "TS parser", IsBackground = true }.Start();

            _supervisor = new Thread(SupervisorLoop) { Name = "Receiver", IsBackground = true };
            _supervisor.Start();
        }

        // RF frequency as QOCAST sends it; the LNB offset from player.json is taken off here.
        // direct = QOCAST's local mode: the frequency goes to the tuner as it is (the Pluto's
        // uplink, no LNB), and LNB power stays off.
        // Returns null when the tuner can receive it, otherwise a short error code for the API.
        public string CheckTune(long rfKhz, long symbolRateKsps, bool direct = false)
        {
            long ifKhz = direct ? rfKhz : rfKhz - _config.lnb_offset_khz;
            if (ifKhz < MinIfKhz || ifKhz > MaxIfKhz)
                return "invalid_frequency";
            if (symbolRateKsps < 1 || symbolRateKsps > 10000)
                return "invalid_symbol_rate";
            return null;
        }

        public void Tune(long rfKhz, long symbolRateKsps, bool direct = false)
        {
            string error = CheckTune(rfKhz, symbolRateKsps, direct);
            if (error != null)
                throw new ArgumentOutOfRangeException(nameof(rfKhz), error);

            long ifKhz = direct ? rfKhz : rfKhz - _config.lnb_offset_khz;
            var request = new TuneRequest(rfKhz, (uint)ifKhz, (uint)symbolRateKsps, direct);
            Session session;
            lock (_lock)
            {
                _lastRequest = request;
                session = _session;
            }

            Log.Information("Tune {Rf} kHz (IF {If} kHz), {Sr} kS/s", rfKhz, ifKhz, symbolRateKsps);
            if (session != null)
                session.Tune(request);
        }

        public void Dispose()
        {
            _stopEvent.Set();
            if (_supervisor != null && !_supervisor.Join(ThreadStopMs * 3))
                Log.Warning("Receiver: supervisor did not stop in time");
        }

        private void SupervisorLoop()
        {
            while (!_stopEvent.WaitOne(0))
            {
                Session session = Session.Open(this);
                if (session == null)
                {
                    SetState(ReceiverState.Disconnected);
                    if (_stopEvent.WaitOne(RetryMs))
                        break;
                    continue;
                }

                TuneRequest resume, resume2;
                lock (_lock)
                {
                    _session = session;
                    resume = _lastRequest;
                    resume2 = _lastRequest2;
                }
                HardwareName = session.HardwareName;
                SetState(resume == null ? ReceiverState.Waiting : ReceiverState.Tuning);
                if (resume != null)
                    session.Tune(resume);
                if (resume2 != null && session.IsPico)
                    session.Tune2(resume2);

                // until the tuner is lost or the player closes
                WaitHandle.WaitAny(new WaitHandle[] { _stopEvent, session.Lost });

                lock (_lock)
                    _session = null;
                session.Close();
                Stream.Clear();

                if (!_stopEvent.WaitOne(0))
                {
                    Log.Warning("Receiver: tuner lost, retrying");
                    SetState(ReceiverState.Disconnected);
                    if (_stopEvent.WaitOne(RetryMs))
                        break;
                }
            }
            SetState(ReceiverState.Disconnected);
        }

        private void SetState(ReceiverState state)
        {
            lock (_lock)
            {
                if (_state == state)
                    return;
                _state = state;
            }
            Log.Information("Receiver: " + state);
            StateChanged?.Invoke(state);
        }

        // ---- one connection to the tuner, from open to unplug/close ----

        private sealed class Session
        {
            private readonly ReceiverService _owner;
            private readonly MTHardwareInterface _hardware;
            private readonly ConcurrentQueue<TunerConfig> _configQueue = new ConcurrentQueue<TunerConfig>();
            private readonly NimThread _nim;
            private readonly Thread _nimThread;
            private readonly Thread _tsThread;
            private readonly ManualResetEvent _lost = new ManualResetEvent(false);
            private readonly AutoResetEvent _tsWake = new AutoResetEvent(false);

            private volatile bool _closing;
            private volatile bool _locked;
            private volatile bool _awaitingRetune;

            // Unsteady lock (it keeps dropping): the demodulator can lock beside the signal
            // (e.g. half a symbol rate off) and stay stuck there. A fresh search fixes it.
            private const int UnsteadyLosses = 3;
            private static readonly TimeSpan UnsteadyWindow = TimeSpan.FromSeconds(15);
            private readonly Queue<DateTime> _lockLosses = new Queue<DateTime>();
            private DateTime _lastFreshSearch = DateTime.MinValue;
            private volatile bool _streaming;

            // channel 2 (PicoTuner only); its thread starts with the first channel-2 tune
            private volatile bool _locked2;
            private volatile bool _awaitingRetune2;
            private volatile bool _streaming2;
            private Thread _ts2Thread;
            private readonly AutoResetEvent _ts2Wake = new AutoResetEvent(false);

            public bool IsPico { get { return _hardware is PicoTunerInterface; } }
            public bool Locked2 { get { return _locked2; } }

            public string HardwareName { get; }
            public WaitHandle Lost { get { return _lost; } }

            private Session(ReceiverService owner, MTHardwareInterface hardware, string name)
            {
                _owner = owner;
                _hardware = hardware;
                HardwareName = name;

                _nim = new NimThread(_configQueue, hardware, OnNimStatus, () => _lost.Set());
                _nimThread = new Thread(_nim.worker_thread) { Name = "Nim", IsBackground = true };
                _tsThread = new Thread(TsLoop) { Name = "TS", IsBackground = true };

                hardware.hw_ts_led(0, false);
                hardware.hw_ts_led(1, false);

                _nimThread.Start();
                _tsThread.Start();
            }

            // same steps as OpenTuner's MinitiounerSource.hardware_init, one tuner only
            private enum Attempt
            {
                MiniTiouner,            // FTDI ports recognised by their names
                PicoTuner,
                MiniTiounerFallback     // FTDI ports with unknown names: 0 and 1, as OpenTuner does
            }

            // receiver_type "auto" (default): MiniTiouner, then PicoTuner, then unknown MiniTiouner variants
            public static Session Open(ReceiverService owner)
            {
                Attempt[] attempts;
                switch (owner._config.receiver_type)
                {
                    case "minitiouner": attempts = new[] { Attempt.MiniTiouner, Attempt.MiniTiounerFallback }; break;
                    case "picotuner": attempts = new[] { Attempt.PicoTuner }; break;
                    default: attempts = new[] { Attempt.MiniTiouner, Attempt.PicoTuner, Attempt.MiniTiounerFallback }; break;
                }

                foreach (Attempt attempt in attempts)
                {
                    Session session = TryOpen(owner, attempt);
                    if (session != null)
                        return session;
                }
                Log.Information("Receiver: no tuner found");
                return null;
            }

            private static Session TryOpen(ReceiverService owner, Attempt attempt)
            {
                MTHardwareInterface hardware = attempt == Attempt.PicoTuner
                    ? (MTHardwareInterface)new PicoTunerInterface()
                    : new FTDIInterface();

                try
                {
                    uint i2c_port = 99, ts_port = 99, ts_port2 = 99;
                    string name = "Unknown";

                    byte err = hardware.hw_detect(ref i2c_port, ref ts_port, ref ts_port2, ref name);
                    if (attempt == Attempt.MiniTiounerFallback)
                    {
                        if (err != 0)           // fewer than two FTDI ports: no MiniTiouner at all
                        {
                            hardware.hw_close();
                            return null;
                        }
                        i2c_port = 0;
                        ts_port = 1;
                        name = "MiniTiouner (unknown variant)";
                    }
                    else if (i2c_port == 99 || ts_port == 99)
                    {
                        hardware.hw_close();
                        return null;
                    }

                    Log.Information("Receiver: opening " + name + " (i2c " + i2c_port + ", ts " + ts_port + ")");
                    // second stream port (tuner 2) is not opened: the player uses tuner 1 only
                    err = hardware.hw_init(i2c_port, ts_port, 99);
                    if (err != 0)
                    {
                        if (attempt != Attempt.PicoTuner)       // PicoTuner: "not plugged in" ends here too
                            Log.Warning("Receiver: open failed, error " + err);
                        hardware.hw_close();
                        return null;
                    }

                    return new Session(owner, hardware, name);
                }
                catch (Exception ex)
                {
                    // missing driver DLL, device busy (another program has the tuner), ...
                    Log.Warning("Receiver: open failed: " + ex.Message);
                    try { hardware.hw_close(); } catch { }
                    return null;
                }
            }

            public void Tune(TuneRequest request)
            {
                PlayerConfig config = _owner._config;
                bool inputB = config.rf_input == "B";
                bool pico = _hardware is PicoTunerInterface;
                byte psu = config.lnb_power == "vertical" ? (byte)1 : config.lnb_power == "horizontal" ? (byte)2 : (byte)0;
                if (request.Direct)
                    psu = 0;        // local mode: an antenna or the Pluto on the input, never LNB voltage

                var tunerConfig = new TunerConfig
                {
                    tuner = 1,
                    frequency = request.IfKhz,
                    symbol_rate = request.SymbolRateKsps,
                    rf_input = inputB ? nim.NIM_INPUT_BOTTOM : nim.NIM_INPUT_TOP,
                    tone_22kHz_P1 = config.tone_22khz,
                    // PicoTuner: one LNB voltage for both inputs, driven only by the "B" channel (as in OpenTuner)
                    lnba_psu = pico || inputB ? (byte)0 : psu,
                    lnbb_psu = pico || inputB ? psu : (byte)0
                };

                // a new station: old stream bytes must not reach the player, and status
                // reads still showing the old station are ignored until the tuner was set
                _awaitingRetune = true;
                StopStreaming();
                _locked = false;
                _owner.SetState(ReceiverState.Tuning);

                _configQueue.Enqueue(tunerConfig);
                _nim.Wake();
            }

            // channel 2: same LNB and input settings as channel 1, demodulator and tuner 2
            public void Tune2(TuneRequest request)
            {
                PlayerConfig config = _owner._config;
                bool inputB = config.rf_input == "B";
                byte psu = config.lnb_power == "vertical" ? (byte)1 : config.lnb_power == "horizontal" ? (byte)2 : (byte)0;
                if (request.Direct)
                    psu = 0;

                var tunerConfig = new TunerConfig
                {
                    tuner = 2,
                    frequency = request.IfKhz,
                    symbol_rate = request.SymbolRateKsps,
                    rf_input = inputB ? nim.NIM_INPUT_BOTTOM : nim.NIM_INPUT_TOP,
                    tone_22kHz_P1 = config.tone_22khz,
                    lnba_psu = 0,
                    lnbb_psu = psu
                };

                lock (_ts2Wake)
                {
                    if (_ts2Thread == null)
                    {
                        _ts2Thread = new Thread(Ts2Loop) { Name = "TS2", IsBackground = true };
                        _ts2Thread.Start();
                    }
                }

                _awaitingRetune2 = true;
                _streaming2 = false;
                _locked2 = false;

                _configQueue.Enqueue(tunerConfig);
                _nim.Wake();
            }

            // channel 2 lock, from the second demodulator
            private void HandleStatus2(TunerStatus status)
            {
                if (_awaitingRetune2)
                {
                    if (!status.T2P1_reset)
                        return;
                    _awaitingRetune2 = false;
                }

                bool locked = status.T2P1_demod_status >= 2 && !status.T2P1_reset;
                if (locked == _locked2)
                    return;

                _locked2 = locked;
                Log.Information("Receiver: channel 2 lock " + (locked ? "on" : "off"));
                _streaming2 = locked;
                if (locked)
                    _ts2Wake.Set();
            }

            // channel 2's stream (endpoint TS1) goes out by UDP in 7-packet datagrams, starting at a
            // packet boundary (three 0x47 sync bytes 188 bytes apart)
            private void Ts2Loop()
            {
                byte[] data = new byte[4096];
                var pending = new List<byte>();
                bool reading = false, synced = false;
                IPEndPoint target = new IPEndPoint(IPAddress.Loopback, _owner.Tuner2UdpPort);

                using (var udp = new UdpClient())
                {
                    try
                    {
                        while (!_closing)
                        {
                            if (!_streaming2)
                            {
                                reading = false;
                                _ts2Wake.WaitOne(500);
                                continue;
                            }

                            if (!reading)
                            {
                                _hardware.transport_flush(PicoTunerInterface.TS1);
                                pending.Clear();
                                synced = false;
                                reading = true;
                            }

                            uint dataRead = 0;
                            if (_hardware.transport_read(PicoTunerInterface.TS1, ref data, ref dataRead) != 0)
                            {
                                Thread.Sleep(10);
                                continue;
                            }

                            if (!_streaming2 || _closing)
                                continue;

                            for (int c = 0; c < dataRead; c++)
                                pending.Add(data[c]);

                            while (!synced && pending.Count >= 377)
                            {
                                if (pending[0] == 0x47 && pending[188] == 0x47 && pending[376] == 0x47)
                                    synced = true;
                                else
                                    pending.RemoveAt(0);
                            }

                            while (synced && pending.Count >= 1316)
                            {
                                try { udp.Send(pending.GetRange(0, 1316).ToArray(), 1316, target); }
                                catch (SocketException) { }     // nobody listens (yet): the stream is simply dropped
                                pending.RemoveRange(0, 1316);
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        if (!_closing)
                            Log.Error(ex, "Receiver: channel 2 stream read stopped");
                    }
                }
            }

            private void OnNimStatus(TunerStatus status)
            {
                if (_closing)
                    return;

                lock (_owner._lock)
                    _owner._lastStatus = status;

                if (_ts2Thread != null)
                {
                    try { HandleStatus2(status); }
                    catch (Exception ex) { Log.Warning("Receiver: channel 2 status: " + ex.Message); }
                }

                // T1P2_reset marks the first status read after the tuner was set
                if (_awaitingRetune)
                {
                    if (!status.T1P2_reset)
                        return;
                    _awaitingRetune = false;
                }

                bool locked = status.T1P2_demod_status >= 2 && !status.T1P2_reset;
                if (locked == _locked)
                    return;

                _locked = locked;
                Log.Information("Receiver: lock " + (locked ? "on" : "off"));
                _hardware.hw_ts_led(0, locked);

                if (locked)
                    StartStreaming();
                else
                    StopStreaming();

                _owner.SetState(locked ? ReceiverState.Locked : ReceiverState.Tuning);

                if (!locked)
                    SearchAgainIfUnsteady();
            }

            private void SearchAgainIfUnsteady()
            {
                DateTime now = DateTime.UtcNow;
                _lockLosses.Enqueue(now);
                while (_lockLosses.Count > 0 && now - _lockLosses.Peek() > UnsteadyWindow)
                    _lockLosses.Dequeue();
                if (_lockLosses.Count < UnsteadyLosses || now - _lastFreshSearch < UnsteadyWindow)
                    return;

                TuneRequest request = _owner.LastRequest;
                if (request == null)
                    return;
                _lastFreshSearch = now;
                _lockLosses.Clear();
                Log.Information("Receiver: lock keeps dropping, searching again");
                Tune(request);
            }

            private void StartStreaming()
            {
                _owner.Stream.Clear();
                _streaming = true;
                _tsWake.Set();
            }

            private void StopStreaming()
            {
                _streaming = false;
                _owner.Stream.Clear();
                lock (_owner._lock)
                    _owner._service = null;
            }

            // replaces OpenTuner's TSThread: reads only while locked, stops when asked
            private void TsLoop()
            {
                byte[] data = new byte[4096];
                bool reading = false;
                long rateBytes = 0;
                DateTime rateSince = DateTime.UtcNow;
                // the stream also goes out by UDP while locked (a web page re-encodes it); nothing is sent unlocked
                UdpTsSender udp = _owner.TsUdpPort > 0 ? new UdpTsSender(_owner.TsUdpPort) : null;

                try
                {
                    while (!_closing)
                    {
                        if (!_streaming)
                        {
                            reading = false;
                            _tsWake.WaitOne(500);
                            continue;
                        }

                        if (!reading)
                        {
                            // throw away what the tuner buffered before the lock
                            _hardware.transport_flush(PicoTunerInterface.TS2);
                            _owner.Stream.Clear();
                            udp?.Reset();
                            reading = true;
                            rateBytes = 0;
                            rateSince = DateTime.UtcNow;
                        }

                        uint dataRead = 0;
                        if (_hardware.transport_read(PicoTunerInterface.TS2, ref data, ref dataRead) != 0)
                        {
                            Thread.Sleep(10);
                            continue;
                        }

                        if (!_streaming || _closing)
                            continue;

                        CircularBuffer parserQueue = _owner._parser.parser_ts_data_queue;
                        for (int c = 0; c < dataRead; c++)
                        {
                            _owner.Stream.Enqueue(data[c]);
                            parserQueue.Enqueue(data[c]);
                        }
                        udp?.Feed(data, (int)dataRead);

                        // stream rate in the log every 10 s, to see that data flows
                        rateBytes += dataRead;
                        double seconds = (DateTime.UtcNow - rateSince).TotalSeconds;
                        if (seconds >= 10)
                        {
                            Log.Information("Receiver: stream {Rate} kbit/s", (int)(rateBytes * 8 / seconds / 1000));
                            rateBytes = 0;
                            rateSince = DateTime.UtcNow;
                        }
                    }
                }
                catch (Exception ex)
                {
                    if (!_closing)
                    {
                        Log.Error(ex, "Receiver: stream read stopped");
                        _lost.Set();
                    }
                }
                finally
                {
                    udp?.Dispose();
                }
            }

            public void Close()
            {
                _closing = true;
                _streaming = false;
                _nim.Stop();
                _tsWake.Set();
                _streaming2 = false;
                _ts2Wake.Set();
                if (_ts2Thread != null && !_ts2Thread.Join(ThreadStopMs))
                    Log.Warning("Receiver: channel 2 thread did not stop in time");

                if (!_nimThread.Join(ThreadStopMs))
                    Log.Warning("Receiver: nim thread did not stop in time");
                if (!_tsThread.Join(ThreadStopMs))
                    Log.Warning("Receiver: TS thread did not stop in time");

                try
                {
                    _hardware.hw_ts_led(0, false);
                }
                catch { }   // tuner may already be unplugged

                try
                {
                    _hardware.hw_close();
                }
                catch (Exception ex)
                {
                    Log.Warning("Receiver: close: " + ex.Message);
                }
                Log.Information("Receiver: tuner released");
            }
        }
    }

    public sealed class TuneRequest
    {
        public TuneRequest(long rfKhz, uint ifKhz, uint symbolRateKsps, bool direct = false)
        {
            RfKhz = rfKhz;
            IfKhz = ifKhz;
            SymbolRateKsps = symbolRateKsps;
            Direct = direct;
        }

        public long RfKhz { get; }
        public uint IfKhz { get; }
        public uint SymbolRateKsps { get; }
        public bool Direct { get; }
    }
}
