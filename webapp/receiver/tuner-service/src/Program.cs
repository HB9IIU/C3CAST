using QocastPlayer.Control;
using QocastPlayer.Receiver;
using Serilog;
using System;
using System.IO;
using System.Net.Sockets;
using System.Threading;

namespace QocastPlayer
{
    // The tuner service: the QOCAST Player's receiver and local control API without its window and video.
    // MiniTiouner / PicoTuner -> locked transport stream by UDP on 127.0.0.1, status and tuning on the local API.
    //
    //   tuner-service.exe --config tuner.json --ts-udp 5001 --parent <pid>
    //
    // --parent: the service closes by itself when that process is gone, so none is left holding the tuner.
    // The tuner can have one owner: the same single-instance name as the QOCAST Player is used, so the two
    // (and OpenTuner) cannot run at the same time.
    internal static class Program
    {
        private static int Main(string[] args)
        {
            // QOCAST (two receivers): each service is pinned to one tuner (QOCAST_TUNER_SERIAL) and may then run beside
            // the other one; its single-instance name and its log file carry that serial.
            string pinned = Environment.GetEnvironmentVariable("QOCAST_TUNER_SERIAL");
            string suffix = string.IsNullOrEmpty(pinned) ? "" : "-" + pinned;
            Log.Logger = new LoggerConfiguration()
                .WriteTo.File(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "tuner-service" + suffix + ".log"),
                              fileSizeLimitBytes: 5 * 1024 * 1024, rollOnFileSizeLimit: true, retainedFileCountLimit: 2)
                .CreateLogger();

            using (var single = new Mutex(true, "QOCAST-Player" + suffix, out bool first))
            {
                if (!first)
                {
                    Log.Information("Another QOCAST Player or tuner service is already running, exiting");
                    Console.Error.WriteLine("Another QOCAST Player or tuner service already owns the tuner.");
                    return 2;
                }

                try
                {
                    return Run(args);
                }
                catch (Exception ex)
                {
                    Log.Fatal(ex, "Tuner service stopped");
                    Console.Error.WriteLine(ex.Message);
                    return 1;
                }
                finally
                {
                    Log.CloseAndFlush();
                }
            }
        }

        private static string Option(string[] args, string name)
        {
            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == name)
                    return args[i + 1];
            }
            return null;
        }

        private static int Run(string[] args)
        {
            string configPath = Option(args, "--config");
            configPath = configPath != null ? Path.GetFullPath(configPath) : PlayerConfig.DefaultPath;
            int.TryParse(Option(args, "--parent"), out int parentPid);
            int.TryParse(Option(args, "--ts-udp"), out int udpPort);
            int.TryParse(Option(args, "--ts-udp2"), out int udpPort2);
            if (udpPort2 == 0) udpPort2 = 5002;
            if (udpPort2 < 1 || udpPort2 > 65535) return 1;
            if (udpPort < 0 || udpPort > 65535)
            {
                Console.Error.WriteLine("--ts-udp must be a port number");
                return 1;
            }

            PlayerConfig config;
            try
            {
                config = PlayerConfig.Load(configPath);
            }
            catch (ConfigException ex)
            {
                Log.Error("Config: " + ex.Message);
                Console.Error.WriteLine(ex.Message);
                return 1;
            }

            Log.Information("Starting, receiver {Receiver}, control port {Port}, stream to UDP {Udp}",
                            config.receiver_type, config.control_port, udpPort);

            var stop = new ManualResetEvent(false);
            Console.CancelKeyPress += (s, e) => { e.Cancel = true; stop.Set(); };

            using (var receiver = new ReceiverService(config) { TsUdpPort = udpPort, Tuner2UdpPort = udpPort2 })
            {
                var control = new ControlServer(receiver, config);
                try
                {
                    control.Start();
                }
                catch (SocketException ex)
                {
                    Log.Error("Control port " + config.control_port + ": " + ex.Message);
                    Console.Error.WriteLine("Port " + config.control_port + " is already in use - is OpenTuner or a QOCAST Player running?");
                    return 1;
                }

                receiver.Start();
                while (!stop.WaitOne(2000))
                {
                    if (ParentGone(parentPid))
                    {
                        Log.Information("The parent program is gone: closing");
                        break;
                    }
                }
                control.Close();
            }

            Log.Information("Bye");
            return 0;
        }

        private static bool ParentGone(int pid)
        {
            if (pid <= 0)
                return false;
            try
            {
                return System.Diagnostics.Process.GetProcessById(pid).HasExited;
            }
            catch (ArgumentException)
            {
                return true;            // no such process
            }
            catch (Exception)
            {
                return false;           // cannot tell: stay open
            }
        }
    }
}
