using Newtonsoft.Json;
using QocastPlayer.Receiver;
using Serilog;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace QocastPlayer.Control
{
    // Copy of OpenTuner's ExtraFeatures\QocastControl\QocastControlServer.cs: same URLs, fields and
    // error codes, so QOCAST's opentuner_client.py works unchanged. Talks to ReceiverService instead
    // of an OpenTuner source; only tuner 1; the IF range is checked before a request is accepted.
    public sealed class QocastTuneRequest
    {
        public string request_id;
        public int tuner = 1;
        public long frequency_khz;
        public long symbol_rate_ksps;
        public bool direct;     // local mode: tune this frequency as it is (no LNB)
    }

    public sealed class QocastTuneResponse
    {
        public bool accepted;
        public string request_id;
        public long generation;
        public string state;
        public string error;
    }

    public sealed class ControlServer
    {
        public const int DefaultPort = 8090;
        private const int MaxRequestBytes = 32 * 1024;
        private const int MaxRememberedRequests = 100;

        private readonly ReceiverService _receiver;
        private readonly PlayerConfig _config;
        private readonly TcpListener _listener;
        private readonly int _port;
        private readonly CancellationTokenSource _cancel = new CancellationTokenSource();
        private readonly object _tuneLock = new object();
        private readonly Dictionary<string, QocastTuneResponse> _responses = new Dictionary<string, QocastTuneResponse>();
        private readonly Queue<string> _responseOrder = new Queue<string>();

        private Task _listenTask;
        private long _generation;
        private DateTime _lastTuneAtUtc = DateTime.MinValue;
        private volatile bool _closed;

        public ControlServer(ReceiverService receiver, PlayerConfig config)
        {
            _receiver = receiver ?? throw new ArgumentNullException(nameof(receiver));
            _config = config;
            _port = config.control_port;
            _listener = new TcpListener(IPAddress.Loopback, _port);
        }

        public void Start()
        {
            _listener.Start(10);
            _listenTask = Task.Run(() => ListenLoop(_cancel.Token));
            Log.Information("Control: listening on http://127.0.0.1:" + _port.ToString() + "/api/v1/");
        }

        public void Close()
        {
            if (_closed)
                return;

            _closed = true;
            _cancel.Cancel();
            _listener.Stop();
            try { _listenTask?.Wait(1000); } catch { }
            _cancel.Dispose();
        }

        private async Task ListenLoop(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    TcpClient client = await _listener.AcceptTcpClientAsync().ConfigureAwait(false);
                    _ = Task.Run(() => HandleClient(client), token);
                }
                catch (ObjectDisposedException) when (token.IsCancellationRequested) { }
                catch (SocketException) when (token.IsCancellationRequested) { }
                catch (Exception ex)
                {
                    Log.Warning(ex, "QOCAST Control: listener error");
                    await Task.Delay(250).ConfigureAwait(false);
                }
            }
        }

        private void HandleClient(TcpClient client)
        {
            using (client)
            {
                try
                {
                    client.ReceiveTimeout = 3000;
                    client.SendTimeout = 3000;
                    using (NetworkStream stream = client.GetStream())
                    using (var reader = new StreamReader(stream, Encoding.ASCII, false, 1024, true))
                    {
                        string requestLine = reader.ReadLine();
                        if (String.IsNullOrWhiteSpace(requestLine))
                            return;

                        string[] requestParts = requestLine.Split(' ');
                        if (requestParts.Length < 2)
                        {
                            WriteJson(stream, 400, new { error = "invalid_request" });
                            return;
                        }

                        string method = requestParts[0].ToUpperInvariant();
                        string path = requestParts[1].Split('?')[0].TrimEnd('/');
                        int contentLength = 0;
                        string header;
                        int headerBytes = requestLine.Length;
                        while (!String.IsNullOrEmpty(header = reader.ReadLine()))
                        {
                            headerBytes += header.Length;
                            if (headerBytes > 16 * 1024)
                            {
                                WriteJson(stream, 431, new { error = "headers_too_large" });
                                return;
                            }

                            int colon = header.IndexOf(':');
                            if (colon > 0 && header.Substring(0, colon).Trim().Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
                                Int32.TryParse(header.Substring(colon + 1).Trim(), out contentLength);
                        }

                        if (contentLength < 0 || contentLength > MaxRequestBytes)
                        {
                            WriteJson(stream, 413, new { error = "request_too_large" });
                            return;
                        }

                        string body = String.Empty;
                        if (contentLength > 0)
                        {
                            char[] buffer = new char[contentLength];
                            int total = 0;
                            while (total < contentLength)
                            {
                                int read = reader.Read(buffer, total, contentLength - total);
                                if (read <= 0)
                                    break;
                                total += read;
                            }
                            body = new string(buffer, 0, total);
                        }

                        Route(stream, method, path, body);
                    }
                }
                catch (Exception ex)
                {
                    Log.Debug(ex, "QOCAST Control: request failed");
                }
            }
        }

        private void Route(NetworkStream stream, string method, string path, string body)
        {
            if (method == "GET" && path == "/api/v1/health")
            {
                bool connected = _receiver.Connected;
                WriteJson(stream, 200, new
                {
                    ok = true,
                    service = "QOCAST Player",
                    api_version = 1,
                    source = "Minitiouner Variant",
                    source_connected = connected,
                    tuner_count = connected ? 1 : 0,
                    minitiouners_found = MiniTiounerCount.Count(),
                    channels = _receiver.SecondChannel ? 2 : 1,
                    tuner2_udp_port = _receiver.Tuner2UdpPort
                });
                return;
            }

            if (method == "GET" && path == "/api/v1/status")
            {
                WriteJson(stream, 200, BuildStatus());
                return;
            }

            if (method == "POST" && path == "/api/v1/tune")
            {
                HandleTune(stream, body);
                return;
            }

            if (method == "POST" && path == "/api/v1/lnb")
            {
                HandleLnb(stream, body);
                return;
            }

            if (method == "POST" && path == "/api/v1/input")
            {
                HandleInput(stream, body);
                return;
            }

            WriteJson(stream, 404, new { error = "not_found" });
        }

        // QOCAST's LNB calibration: new LNB offset (kHz). Saved in player.json, and the
        // current station is tuned again with it.
        private void HandleLnb(NetworkStream stream, string body)
        {
            long offsetKhz;
            try
            {
                offsetKhz = (long)Newtonsoft.Json.Linq.JObject.Parse(body)["lnb_offset_khz"];
            }
            catch (Exception)
            {
                WriteJson(stream, 400, new { ok = false, error = "lnb_offset_khz_required" });
                return;
            }
            if (offsetKhz < 1000000 || offsetKhz > 20000000)
            {
                WriteJson(stream, 400, new { ok = false, error = "invalid_lnb_offset" });
                return;
            }

            lock (_tuneLock)
            {
                long previous = _config.lnb_offset_khz;
                _config.lnb_offset_khz = offsetKhz;
                try
                {
                    _config.Save();
                }
                catch (Exception ex)
                {
                    Log.Warning("Control: could not save the LNB offset: " + ex.Message);
                }
                Log.Information("Control: LNB offset {Previous} -> {Offset} kHz", previous, offsetKhz);

                TuneRequest request = _receiver.LastRequest;
                if (request != null && _receiver.CheckTune(request.RfKhz, request.SymbolRateKsps, request.Direct) == null)
                {
                    _receiver.Tune(request.RfKhz, request.SymbolRateKsps, request.Direct);
                    _lastTuneAtUtc = DateTime.UtcNow;
                }
            }
            WriteJson(stream, 200, new { ok = true, lnb_offset_khz = offsetKhz });
        }

        // QOCAST's Setup page: which RF input the tuner listens on, and the LNB voltage on it
        // (off, vertical = 13 V, horizontal = 18 V). Saved in player.json, and the current
        // station is tuned again with it.
        private void HandleInput(NetworkStream stream, string body)
        {
            string rfInput, lnbPower;
            try
            {
                var json = Newtonsoft.Json.Linq.JObject.Parse(body);
                rfInput = (string)json["rf_input"] ?? _config.rf_input;
                lnbPower = (string)json["lnb_power"] ?? _config.lnb_power;
            }
            catch (Exception)
            {
                WriteJson(stream, 400, new { ok = false, error = "invalid_json" });
                return;
            }
            if (rfInput != "A" && rfInput != "B")
            {
                WriteJson(stream, 400, new { ok = false, error = "invalid_rf_input" });
                return;
            }
            if (lnbPower != "off" && lnbPower != "vertical" && lnbPower != "horizontal")
            {
                WriteJson(stream, 400, new { ok = false, error = "invalid_lnb_power" });
                return;
            }

            lock (_tuneLock)
            {
                _config.rf_input = rfInput;
                _config.lnb_power = lnbPower;
                try
                {
                    _config.Save();
                }
                catch (Exception ex)
                {
                    Log.Warning("Control: could not save the RF input: " + ex.Message);
                }
                Log.Information("Control: RF input {Input}, LNB power {Power}", rfInput, lnbPower);

                TuneRequest request = _receiver.LastRequest;
                if (request != null && _receiver.CheckTune(request.RfKhz, request.SymbolRateKsps, request.Direct) == null)
                {
                    _receiver.Tune(request.RfKhz, request.SymbolRateKsps, request.Direct);
                    _lastTuneAtUtc = DateTime.UtcNow;
                }
            }
            WriteJson(stream, 200, new { ok = true, rf_input = rfInput, lnb_power = lnbPower });
        }

        private object BuildStatus()
        {
            bool connected = _receiver.Connected;
            var receiver = RxInfo.Build(_receiver, _config);   // the picture (codec, size) is not known here: nothing plays in this service
            TuneRequest request = _receiver.LastRequest;
            string state;
            if (!connected)
                state = "disconnected";
            else if (receiver.locked)
                state = "locked";
            else if ((DateTime.UtcNow - _lastTuneAtUtc).TotalSeconds < 15)
                state = "tuning";
            else
                state = "idle";

            return new
            {
                ok = true,
                api_version = 1,
                generation = Interlocked.Read(ref _generation),
                state,
                source_connected = connected,
                requested_frequency_khz = request?.RfKhz,
                requested_symbol_rate_ksps = (long?)request?.SymbolRateKsps,
                rf_input_setting = _config.rf_input,
                lnb_power_setting = _config.lnb_power,
                receiver,
                tuner2 = BuildTuner2()
            };
        }

        // channel 2 of a PicoTuner, null for any other tuner
        private object BuildTuner2()
        {
            if (!_receiver.SecondChannel)
                return null;
            TuneRequest request = _receiver.LastRequest2;
            opentuner.TunerStatus status = _receiver.LastStatus;
            bool locked = _receiver.Tuner2Locked;
            return new
            {
                locked,
                requested_frequency_khz = request?.RfKhz,
                requested_symbol_rate_ksps = (long?)request?.SymbolRateKsps,
                mer_db = locked && status != null ? (double?)(Convert.ToDouble(status.T2P1_mer) / 10) : null
            };
        }

        private void HandleTune(NetworkStream stream, string body)
        {
            QocastTuneRequest request;
            try
            {
                request = JsonConvert.DeserializeObject<QocastTuneRequest>(body);
            }
            catch (JsonException)
            {
                WriteJson(stream, 400, new { accepted = false, error = "invalid_json" });
                return;
            }

            string validationError = Validate(request);
            if (validationError != null)
            {
                WriteJson(stream, 400, new { accepted = false, request_id = request?.request_id, error = validationError });
                return;
            }

            lock (_tuneLock)
            {
                if (_responses.TryGetValue(request.request_id, out QocastTuneResponse previous))
                {
                    WriteJson(stream, previous.accepted ? 200 : 409, previous);
                    return;
                }

                if (!_receiver.Connected)
                {
                    var unavailable = Remember(new QocastTuneResponse
                    {
                        accepted = false,
                        request_id = request.request_id,
                        generation = Interlocked.Read(ref _generation),
                        state = "disconnected",
                        error = "source_not_connected"
                    });
                    WriteJson(stream, 409, unavailable);
                    return;
                }

                long generation = Interlocked.Increment(ref _generation);
                try
                {
                    if (request.tuner == 2)
                    {
                        _receiver.Tune2(request.frequency_khz, request.symbol_rate_ksps, request.direct);
                    }
                    else
                    {
                        _receiver.Tune(request.frequency_khz, request.symbol_rate_ksps, request.direct);
                        _lastTuneAtUtc = DateTime.UtcNow;
                    }

                    var accepted = Remember(new QocastTuneResponse
                    {
                        accepted = true,
                        request_id = request.request_id,
                        generation = generation,
                        state = "tuning"
                    });
                    Log.Information("Control: tune request {RequestId}, generation {Generation}, tuner {Tuner}, {Frequency} kHz, {SymbolRate} kS/s",
                        request.request_id, generation, request.tuner, request.frequency_khz, request.symbol_rate_ksps);
                    WriteJson(stream, 202, accepted);
                }
                catch (Exception ex)
                {
                    Log.Error(ex, "QOCAST Control: tune request failed");
                    var failed = Remember(new QocastTuneResponse
                    {
                        accepted = false,
                        request_id = request.request_id,
                        generation = generation,
                        state = "error",
                        error = "tune_failed"
                    });
                    WriteJson(stream, 500, failed);
                }
            }
        }

        private string Validate(QocastTuneRequest request)
        {
            if (request == null)
                return "request_required";
            if (String.IsNullOrWhiteSpace(request.request_id) || request.request_id.Length > 80)
                return "invalid_request_id";
            if (request.tuner != 1 && !(request.tuner == 2 && _receiver.SecondChannel))
                return "invalid_tuner";
            if (request.frequency_khz < 100000 || request.frequency_khz > UInt32.MaxValue)
                return "invalid_frequency";
            if (request.symbol_rate_ksps < 1 || request.symbol_rate_ksps > 10000)
                return "invalid_symbol_rate";
            // RF minus LNB offset must be a frequency the tuner can receive
            return _receiver.CheckTune(request.frequency_khz, request.symbol_rate_ksps, request.direct);
        }

        private QocastTuneResponse Remember(QocastTuneResponse response)
        {
            _responses[response.request_id] = response;
            _responseOrder.Enqueue(response.request_id);
            while (_responseOrder.Count > MaxRememberedRequests)
            {
                string oldest = _responseOrder.Dequeue();
                _responses.Remove(oldest);
            }
            return response;
        }

        private static void WriteJson(NetworkStream stream, int statusCode, object value)
        {
            string json = JsonConvert.SerializeObject(value);
            byte[] body = Encoding.UTF8.GetBytes(json);
            string statusText = statusCode == 200 ? "OK" :
                                statusCode == 202 ? "Accepted" :
                                statusCode == 400 ? "Bad Request" :
                                statusCode == 404 ? "Not Found" :
                                statusCode == 409 ? "Conflict" :
                                statusCode == 413 ? "Payload Too Large" :
                                statusCode == 431 ? "Request Header Fields Too Large" : "Internal Server Error";
            string headers = "HTTP/1.1 " + statusCode.ToString() + " " + statusText + "\r\n" +
                             "Content-Type: application/json; charset=utf-8\r\n" +
                             "Content-Length: " + body.Length.ToString() + "\r\n" +
                             "Cache-Control: no-store\r\n" +
                             "Connection: close\r\n\r\n";
            byte[] headerBytes = Encoding.ASCII.GetBytes(headers);
            stream.Write(headerBytes, 0, headerBytes.Length);
            stream.Write(body, 0, body.Length);
            stream.Flush();
        }
    }
}
