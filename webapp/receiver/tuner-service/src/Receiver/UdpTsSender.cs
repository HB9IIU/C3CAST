using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Sockets;

namespace QocastPlayer.Receiver
{
    // Sends the locked transport stream to a loopback UDP port in 7-packet datagrams, starting at a packet
    // boundary (three 0x47 sync bytes 188 bytes apart). Same framing as the Player's second channel.
    internal sealed class UdpTsSender : IDisposable
    {
        private const int PacketSize = 188;
        private const int DatagramSize = 7 * PacketSize;

        private readonly UdpClient _udp = new UdpClient();
        private readonly IPEndPoint _target;
        private readonly List<byte> _pending = new List<byte>();
        private bool _synced;

        public UdpTsSender(int port)
        {
            _target = new IPEndPoint(IPAddress.Loopback, port);
        }

        // a new lock: forget what was waiting
        public void Reset()
        {
            _pending.Clear();
            _synced = false;
        }

        public void Feed(byte[] data, int count)
        {
            for (int i = 0; i < count; i++)
                _pending.Add(data[i]);

            while (!_synced && _pending.Count >= 2 * PacketSize + 1)
            {
                if (_pending[0] == 0x47 && _pending[PacketSize] == 0x47 && _pending[2 * PacketSize] == 0x47)
                    _synced = true;
                else
                    _pending.RemoveAt(0);
            }

            while (_synced && _pending.Count >= DatagramSize)
            {
                try
                {
                    _udp.Send(_pending.GetRange(0, DatagramSize).ToArray(), DatagramSize, _target);
                }
                catch (SocketException)
                {
                    // nobody listens (yet): the stream is simply dropped
                }
                _pending.RemoveRange(0, DatagramSize);
            }
        }

        public void Dispose()
        {
            _udp.Close();
        }
    }
}
