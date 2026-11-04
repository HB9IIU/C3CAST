using FTD2XX_NET;
using System;

namespace QocastPlayer
{
    // How many MiniTiouners are plugged in, also those another program has open. Each one shows
    // as two FTDI ports (A = control, B = data). Nothing is opened.
    public static class MiniTiounerCount
    {
        private static readonly string[] ControlPorts =
        {
            "NIM tuner A", "MiniTiouner_Pro_TS2 A", "MiniTiouner A", "Minitiouner S A", "MiniTiouner-Express A"
        };

        private static int _count;
        private static DateTime _checked = DateTime.MinValue;

        public static int Count()
        {
            if ((DateTime.UtcNow - _checked).TotalSeconds < 3)
                return _count;
            _checked = DateTime.UtcNow;
            try
            {
                var ftdi = new FTDI();
                uint devices = 0;
                if (ftdi.GetNumberOfDevices(ref devices) != FTDI.FT_STATUS.FT_OK || devices == 0)
                    return _count = 0;
                var list = new FTDI.FT_DEVICE_INFO_NODE[devices];
                if (ftdi.GetDeviceList(list) != FTDI.FT_STATUS.FT_OK)
                    return _count = 0;
                // Ports this program can see by name: the A ports. A port another program (the second
                // Player) has open shows no name and no type, only "open": two of those are one tuner.
                int found = 0, hidden = 0;
                foreach (FTDI.FT_DEVICE_INFO_NODE node in list)
                {
                    string name = node == null ? null : node.Description;
                    if (string.IsNullOrEmpty(name))
                    {
                        if (node != null && (node.Flags & 1) != 0)
                            hidden++;
                        continue;
                    }
                    foreach (string port in ControlPorts)
                    {
                        if (name.Contains(port))
                        {
                            found++;
                            break;
                        }
                    }
                }
                found += hidden / 2;
                return _count = found;
            }
            catch (Exception)
            {
                return _count = 0;
            }
        }
    }
}
