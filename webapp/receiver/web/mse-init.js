/** Which tracks does a fragmented MP4 stream carry? Read from its initialization segment.
 * Media Source Extensions rejects a stream whose tracks differ from the codecs announced to the
 * SourceBuffer, and some stations send no audio, so the announcement must follow the stream.
 *
 *   MseInit.mimeFor(bytes)  ->  a MIME type string, or null while the moov box is still incomplete;
 *                               throws if the stream has no video or audio track.
 * The video is always H.264 Constrained Baseline 3.1 and the audio AAC-LC (see mse_player.ffmpeg_command).
 */
(function (scope) {
  'use strict';
  const VIDEO = 'avc1.42c01f', AUDIO = 'mp4a.40.2';

  function contains(bytes, tag) {
    const a = tag.charCodeAt(0), b = tag.charCodeAt(1), c = tag.charCodeAt(2), d = tag.charCodeAt(3);
    for (let i = 0; i + 3 < bytes.length; i += 1) {
      if (bytes[i] === a && bytes[i + 1] === b && bytes[i + 2] === c && bytes[i + 3] === d) return true;
    }
    return false;
  }

  function mimeFor(bytes) {
    let at = 0;
    while (at + 8 <= bytes.length) {
      const size = ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;
      const type = String.fromCharCode(bytes[at + 4], bytes[at + 5], bytes[at + 6], bytes[at + 7]);
      if (size < 8) throw new Error('The stream does not start with a valid MP4 header');
      if (type === 'moov') {
        if (at + size > bytes.length) return null;          // the rest of the header has not arrived yet
        const moov = bytes.subarray(at, at + size);
        const video = contains(moov, 'avc1'), audio = contains(moov, 'mp4a');
        if (video && audio) return `video/mp4; codecs="${VIDEO}, ${AUDIO}"`;
        if (video) return `video/mp4; codecs="${VIDEO}"`;
        if (audio) return `audio/mp4; codecs="${AUDIO}"`;
        throw new Error('The stream has no video or audio track');
      }
      at += size;
    }
    return null;
  }

  const api = { mimeFor };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else scope.MseInit = api;
}(globalThis));
