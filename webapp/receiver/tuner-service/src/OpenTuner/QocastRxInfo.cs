namespace opentuner.ExtraFeatures.QocastStream
{
    // tuner 1 status as shown in the Properties panel, posted to the Qocast as JSON (POST /api/rx/info).
    // field names are the JSON keys agreed with the Qocast app - don't rename them (lpdc_errors included).
    // null = value unknown.
    public class QocastRxInfo
    {
        public int tuner = 1;
        public bool locked = false;
        public string demod_state;
        public double? db_margin;
        public double? mer_db;
        public int? rf_level_db;
        public string rf_input;
        public long? requested_freq_khz;
        public long? if_freq_khz;
        public long? symbol_rate_ksps;
        public long? freq_offset_khz;
        public string modcod;
        public int? lna_gain;
        public long? ber;
        public long? carrier_offset_hz;
        public string stream_format;
        public string service_name;
        public string service_provider;
        public long? null_packets_percent;
        public string video_codec;
        public string video_resolution;
        public string audio_codec;
        public string audio_rate;
        public long? lpdc_errors;
        public string lnb_a_power;
        public string lnb_b_power;
        public string hardware_interface;
        // the last symbols the demodulator saw, [i, q] as raw signed bytes (0..255); only while locked
        public int[][] constellation;

        public QocastRxInfo Clone()
        {
            return (QocastRxInfo)MemberwiseClone();
        }
    }
}
