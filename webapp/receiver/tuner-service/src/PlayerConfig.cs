using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace QocastPlayer
{
    public sealed class WindowBounds
    {
        public int x = 100;
        public int y = 100;
        public int width = 960;
        public int height = 540;
        // true until a window place comes from player.json: the first start puts the window in
        // the bottom right corner, small, so the browser with the QOCAST page stays in front
        [Newtonsoft.Json.JsonIgnore] public bool IsDefault = true;
    }

    // player.json next to qocast-player.exe, optional: without it the defaults below are used
    // (tuner found by itself). Checked completely before the tuner is touched: a wrong or
    // unknown entry stops the player with a short message, nothing is guessed.
    public sealed class PlayerConfig
    {
        public const string FileName = "player.json";

        public string receiver_type = "auto";   // "auto", "minitiouner" or "picotuner"
        public long lnb_offset_khz = 9750000;
        public string rf_input = "A";           // "A" or "B"
        public string lnb_power = "off";        // "off", "vertical" or "horizontal"
        public bool tone_22khz = false;
        public int control_port = 8090;
        public string qocast_info_url = null;   // null = no status to QOCAST
        public int volume = 60;
        public bool muted = false;
        public bool always_on_top = true;
        public bool title_bar = false;          // false: only the picture, moved by dragging it
        public WindowBounds window = new WindowBounds();

        [JsonIgnore]
        public string Path { get; private set; }

        public static string DefaultPath
        {
            get { return System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, FileName); }
        }

        public static PlayerConfig Load(string path)
        {
            if (!File.Exists(path))
                return new PlayerConfig { Path = path };

            JObject root;
            try
            {
                root = JObject.Parse(File.ReadAllText(path, Encoding.UTF8));
            }
            catch (JsonException ex)
            {
                throw new ConfigException(FileName + " is not valid JSON: " + ex.Message);
            }

            var config = new PlayerConfig { Path = path };
            var errors = new List<string>();
            var known = new HashSet<string> { "receiver_type", "lnb_offset_khz", "rf_input", "lnb_power", "tone_22khz",
                                              "control_port", "qocast_info_url", "volume", "muted", "always_on_top", "title_bar", "window" };

            foreach (JProperty property in root.Properties())
            {
                if (!known.Contains(property.Name))
                    errors.Add("unknown entry \"" + property.Name + "\"");
            }

            config.receiver_type = ReadChoice(root, "receiver_type", config.receiver_type, errors, "auto", "minitiouner", "picotuner");
            config.lnb_offset_khz = ReadLong(root, "lnb_offset_khz", config.lnb_offset_khz, 0, 100000000, errors);
            config.rf_input = ReadChoice(root, "rf_input", config.rf_input, errors, "A", "B");
            config.lnb_power = ReadChoice(root, "lnb_power", config.lnb_power, errors, "off", "vertical", "horizontal");
            config.tone_22khz = ReadBool(root, "tone_22khz", config.tone_22khz, errors);
            config.control_port = (int)ReadLong(root, "control_port", config.control_port, 1, 65535, errors);
            config.qocast_info_url = ReadUrl(root, "qocast_info_url", errors);
            config.volume = (int)ReadLong(root, "volume", config.volume, 0, 100, errors);
            config.muted = ReadBool(root, "muted", config.muted, errors);
            config.always_on_top = ReadBool(root, "always_on_top", config.always_on_top, errors);
            config.title_bar = ReadBool(root, "title_bar", config.title_bar, errors);
            config.window = ReadWindow(root, errors);

            if (errors.Count > 0)
                throw new ConfigException("Please correct " + FileName + ":\n- " + String.Join("\n- ", errors));

            return config;
        }

        // write to a temporary file first, then swap: a crash never leaves half a file
        public void Save()
        {
            string json = JsonConvert.SerializeObject(this, Formatting.Indented);
            string temp = Path + ".tmp";
            File.WriteAllText(temp, json + Environment.NewLine, new UTF8Encoding(false));
            if (File.Exists(Path))
                File.Replace(temp, Path, null);
            else
                File.Move(temp, Path);
        }

        private static string ReadChoice(JObject root, string name, string fallback, List<string> errors, params string[] choices)
        {
            JToken token = root[name];
            if (token == null || token.Type == JTokenType.Null)
            {
                if (fallback == null)
                    errors.Add(name + " is missing (" + String.Join(" or ", choices) + ")");
                return fallback;
            }
            if (token.Type == JTokenType.String)
            {
                foreach (string choice in choices)
                {
                    if (String.Equals((string)token, choice, StringComparison.OrdinalIgnoreCase))
                        return choice;
                }
            }
            errors.Add(name + " must be " + String.Join(" or ", choices) + ", not " + token.ToString(Formatting.None));
            return fallback;
        }

        private static long ReadLong(JObject root, string name, long fallback, long min, long max, List<string> errors)
        {
            JToken token = root[name];
            if (token == null)
                return fallback;
            if (token.Type == JTokenType.Integer)
            {
                long value = (long)token;
                if (value >= min && value <= max)
                    return value;
            }
            errors.Add(name + " must be a whole number from " + min + " to " + max + ", not " + token.ToString(Formatting.None));
            return fallback;
        }

        private static bool ReadBool(JObject root, string name, bool fallback, List<string> errors)
        {
            JToken token = root[name];
            if (token == null)
                return fallback;
            if (token.Type == JTokenType.Boolean)
                return (bool)token;
            errors.Add(name + " must be true or false, not " + token.ToString(Formatting.None));
            return fallback;
        }

        private static string ReadUrl(JObject root, string name, List<string> errors)
        {
            JToken token = root[name];
            if (token == null || token.Type == JTokenType.Null)
                return null;
            if (token.Type == JTokenType.String &&
                Uri.TryCreate((string)token, UriKind.Absolute, out Uri uri) &&
                (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
                return (string)token;
            errors.Add(name + " must be an http:// address or null, not " + token.ToString(Formatting.None));
            return null;
        }

        private static WindowBounds ReadWindow(JObject root, List<string> errors)
        {
            var bounds = new WindowBounds();
            JToken token = root["window"];
            if (token == null || token.Type == JTokenType.Null)
                return bounds;
            if (!(token is JObject window))
            {
                errors.Add("window must be { \"x\", \"y\", \"width\", \"height\" }");
                return bounds;
            }
            foreach (JProperty property in window.Properties())
            {
                if (property.Name != "x" && property.Name != "y" && property.Name != "width" && property.Name != "height")
                    errors.Add("unknown entry \"window." + property.Name + "\"");
            }
            bounds.IsDefault = false;
            bounds.x = (int)ReadLong(window, "x", bounds.x, -100000, 100000, errors);
            bounds.y = (int)ReadLong(window, "y", bounds.y, -100000, 100000, errors);
            bounds.width = (int)ReadLong(window, "width", bounds.width, 160, 100000, errors);
            bounds.height = (int)ReadLong(window, "height", bounds.height, 90, 100000, errors);
            return bounds;
        }
    }

    public sealed class ConfigException : Exception
    {
        public ConfigException(string message) : base(message) { }
    }
}
