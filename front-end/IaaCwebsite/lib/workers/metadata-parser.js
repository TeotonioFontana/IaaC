const { parentPort, workerData } = require('worker_threads');

/**
 * Parse metadata from buffer in a worker thread
 * This handles the CPU-intensive synchronous buffer parsing
 */

const parser = {

    JPEG: (buff) => {
        const sof = [0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf, 0xde];
        let pos = 0;
        let width = null, height = null;

        while (buff[pos++] == 0xff) {
            let marker = buff[pos++];
            let size = buff.readUInt16BE(pos);

            if (marker == 0xda) break;

            if (sof.includes(marker)) {
                height = buff.readUInt16BE(pos + 3);
                width = buff.readUInt16BE(pos + 5);
                break;
            }

            pos += size;
        }

        return { width, height };
    },

    TIFF: (buff) => {
        const le = buff.toString('ascii', 0, 2) == 'II';
        let width = null, height = null;

        // Helper functions that take absolute position as parameter
        const readUInt16 = (pos) => {
            if (pos + 2 > buff.length) return 0;
            return buff[le ? 'readUInt16LE' : 'readUInt16BE'](pos);
        };
        const readUInt32 = (pos) => {
            if (pos + 4 > buff.length) return 0;
            return buff[le ? 'readUInt32LE' : 'readUInt32BE'](pos);
        };

        // Read offset to first IFD (Image File Directory)
        let ifdOffset = readUInt32(4);

        // Process IFD entries
        while (ifdOffset > 0 && ifdOffset < buff.length) {
            // Read number of directory entries
            let entries = readUInt16(ifdOffset);
            if (entries == 0 || entries > 1000) break;  // Safety check

            // Each IFD entry is 12 bytes
            let pos = ifdOffset + 2;  // Skip entry count

            for (let i = 0; i < entries; i++) {
                if (pos + 12 > buff.length) break;

                let tag = readUInt16(pos);
                let type = readUInt16(pos + 2);
                let count = readUInt32(pos + 4);
                let value = readUInt32(pos + 8);

                if (tag == 256) width = value;   // ImageWidth
                if (tag == 257) height = value;  // ImageHeight

                if (width && height) {
                    return { width, height };
                }

                pos += 12;
            }

            // Get offset to next IFD
            if (pos + 4 > buff.length) break;
            ifdOffset = readUInt32(pos);
        }

        return { width, height };
    },

    MOV: (buff, startPos = 0) => {
        let pos = startPos;
        let width = null, height = null, duration = null;
        let maxIterations = 1000;  // Safety limit to prevent infinite loops
        let iterations = 0;

        while (pos < buff.length && iterations++ < maxIterations) {
            // Check if we have enough bytes for atom header
            if (pos + 8 > buff.length) break;

            let size = buff.readUInt32BE(pos);
            let name = buff.toString('ascii', pos + 4, pos + 8);

            // Handle special size values
            if (size == 0) {
                // Size 0 means "rest of file"
                size = buff.length - pos;
            } else if (size == 1) {
                // Extended size (64-bit) - rarely used
                if (pos + 16 > buff.length) break;
                size = Number(buff.readBigUInt64BE(pos + 8));
            } else if (size < 8) {
                // Invalid size (atoms must be at least 8 bytes: 4 for size + 4 for type)
                break;
            }

            if (name == 'mvhd') {
                if (pos + 32 > buff.length) break;
                let scale = buff.readUInt32BE(pos + 8 + 12);  // Skip 8-byte header + 12 bytes to timescale
                let dur = buff.readUInt32BE(pos + 8 + 16);    // Skip 8-byte header + 16 bytes to duration
                if (scale > 0) {
                    duration = ~~(dur / scale);
                }
            }

            if (name == 'tkhd') {
                if (pos + 92 > buff.length) break;
                // Matrix values are 32-bit fixed-point at offset +40 from data start
                let m0 = buff.readUInt32BE(pos + 8 + 40);     // matrix[0] - horizontal scale (offset +40)
                let m4 = buff.readUInt32BE(pos + 8 + 56);     // matrix[4] - vertical scale (offset +56)
                // Width and height are 32-bit fixed-point after matrix
                let w = buff.readUInt32BE(pos + 8 + 76);      // width in 16.16 fixed point (offset +76)
                let h = buff.readUInt32BE(pos + 8 + 80);      // height in 16.16 fixed point (offset +80)
                if (w > 0 && h > 0) {
                    // If matrix values are present and non-zero, use them for scaling
                    if (m0 > 0 && m4 > 0) {
                        width = w / m0;
                        height = h / m4;
                    } else {
                        // Otherwise just convert from fixed-point to integer
                        width = w >> 16;
                        height = h >> 16;
                    }
                    return { width, height, duration };
                }
            }

            if (name == 'moov' || name == 'trak') {
                const result = parser.MOV(buff, pos + 8);
                if (result.width) {
                    // Merge results: use duration from current scope if available
                    return {
                        width: result.width,
                        height: result.height,
                        duration: result.duration || duration
                    };
                }
            }

            pos += size;
        }

        return { width, height, duration };
    },

    OGG: (buff) => {
        let pos = 0;
        let vorbis = null;
        let width = null, height = null, duration = null;
        let maxIterations = 10000; // Safety limit
        let iterations = 0;

        while (pos < buff.length && iterations++ < maxIterations && buff.toString('ascii', pos, pos + 4) == 'OggS') {
            let version = buff[pos + 4];
            let b = buff[pos + 5];
            let continuation = !!(b & 0x01);
            let bos = !!(b & 0x02);
            let eos = !!(b & 0x04);
            let position = Number(buff.readBigUInt64LE(pos + 6));
            let serial = buff.readUInt32LE(pos + 14);
            let pageNumber = buff.readUInt32LE(pos + 18);
            let checksum = buff.readUInt32LE(pos + 22);
            let pageSegments = buff[pos + 26];
            let lacing = buff.slice(pos + 27, pos + 27 + pageSegments);
            let pageSize = lacing.reduce((p, v) => p + v, 0);
            let start = pos + 27 + pageSegments;
            let pageHeader = buff.slice(start, start + 7);

            // Check for Vorbis identification header (0x01 + "vorbis")
            if (pageHeader.compare(Buffer.from([0x01, 0x76, 0x6F, 0x72, 0x62, 0x69, 0x73])) == 0) {
                vorbis = { serial, sampleRate: buff.readUInt32LE(start + 12) };
            }

            // Check for Theora identification header (0x80 + "theora")
            if (pageHeader.compare(Buffer.from([0x80, 0x74, 0x68, 0x65, 0x6F, 0x72, 0x61])) == 0) {
                // Read version bytes (3 bytes at offset 7-9)
                let verMajor = buff[start + 7];
                let verMinor = buff[start + 8];
                let verRev = buff[start + 9];
                let version = (verMajor << 16) | (verMinor << 8) | verRev;

                width = buff.readUInt16BE(start + 10) << 4;
                height = buff.readUInt16BE(start + 12) << 4;

                // Theora 3.2.0 and later have picture region (display dimensions)
                if (version >= 0x030200) {
                    // Read 24-bit display width and height
                    let w = (buff[start + 14] << 16) | (buff[start + 15] << 8) | buff[start + 16];
                    let h = (buff[start + 17] << 16) | (buff[start + 18] << 8) | buff[start + 19];

                    // Use display dimensions if they're within 16 pixels of frame dimensions
                    if (w <= width && w > width - 16 && h <= height && h > height - 16) {
                        width = w;
                        height = h;
                    }
                }
            }

            if (eos && vorbis && serial == vorbis.serial) {
                duration = ~~(position / vorbis.sampleRate);
            }

            // Move to next page: current header (27) + segment table (pageSegments) + page data (pageSize)
            pos = start + pageSize;
        }

        return { width, height, duration };
    },

    MP3: (buff) => {
        const versions = [2.5, 0, 2, 1];
        const layers = [0, 3, 2, 1];
        const bitrates = [
            [ // version 2.5
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0, 8,16,24, 32, 40, 48, 56, 64, 80, 96,112,128,144,160], // layer 3
                [0, 8,16,24, 32, 40, 48, 56, 64, 80, 96,112,128,144,160], // layer 2
                [0,32,48,56, 64, 80, 96,112,128,144,160,176,192,224,256]  // layer 1
            ],
            [ // reserved
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0]  // reserved
            ],
            [ // version 2
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0, 8,16,24, 32, 40, 48, 56, 64, 80, 96,112,128,144,160], // layer 3
                [0, 8,16,24, 32, 40, 48, 56, 64, 80, 96,112,128,144,160], // layer 2
                [0,32,48,56, 64, 80, 96,112,128,144,160,176,192,224,256]  // layer 1
            ],
            [ // version 1
                [0, 0, 0, 0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0], // reserved
                [0,32,40,48, 56, 64, 80, 96,112,128,160,192,224,256,320], // layer 3
                [0,32,48,56, 64, 80, 96,112,128,160,192,224,256,320,384], // layer 2
                [0,32,64,96,128,160,192,224,256,288,320,352,384,416,448]  // layer 1
            ]
        ];
        const srates = [
            [11025, 12000,  8000, 0], // mpeg 2.5
            [    0,     0,     0, 0], // reserved
            [22050, 24000, 16000, 0], // mpeg 2
            [44100, 48000, 32000, 0]  // mpeg 1
        ];
        const tsamples = [
            [0,  576, 1152, 384], // mpeg 2.5
            [0,    0,    0,   0], // reserved
            [0,  576, 1152, 384], // mpeg 2
            [0, 1152, 1152, 384]  // mpeg 1
        ];
        const slotSizes = [0, 1, 1, 4];
        const modes = ['stereo', 'joint_stereo', 'dual_channel', 'mono'];

        let duration = 0;
        let count = 0;
        let skip = 0;
        let pos = 0;

        while (pos < buff.length) {
            let start = pos;

            if (buff.toString('ascii', pos, pos + 4) == 'TAG+') {
                skip += 227;
                pos += 227;
            } else if (buff.toString('ascii', pos, pos + 3) == 'TAG') {
                skip += 128;
                pos += 128;
            } else if (buff.toString('ascii', pos, pos + 3) == 'ID3') {
                let bytes = buff.readUInt32BE(pos + 6);
                let size = 10 + (bytes[0] << 21 | bytes[1] << 14 | bytes[2] << 7 | bytes[3]);
                skip += size;
                pos += size;
            } else {
                let hdr = buff.slice(pos, pos + 4);

                while (pos < buff.length && !(hdr[0] == 0xff && (hdr[1] & 0xe0) == 0xe0)) {
                    pos++;
                    hdr = buff.slice(pos, pos + 4);
                }

                let ver = (hdr[1] & 0x18) >> 3;
                let lyr = (hdr[1] & 0x06) >> 1;
                let pad = (hdr[2] & 0x02) >> 1;
                let brx = (hdr[2] & 0xf0) >> 4;
                let srx = (hdr[2] & 0x0c) >> 2;
                let mdx = (hdr[3] & 0xc0) >> 6;

                let version = versions[ver];
                let layer = layers[lyr];
                let bitrate = bitrates[ver][lyr][brx] * 1000;
                let samprate = srates[ver][srx];
                let samples = tsamples[ver][lyr];
                let slotSize = slotSizes[lyr];
                let mode = modes[mdx];
                let fsize = ~~(((samples / 8 * bitrate) / samprate) + (pad ? slotSize : 0));

                count++;

                if (count == 1) {
                    if (layer != 3) {
                        pos += 2;
                    } else {
                        if (mode != 'mono') {
                            if (version == 1) {
                                pos += 32;
                            } else {
                                pos += 17;
                            }
                        } else {
                            if (version == 1) {
                                pos += 17;
                            } else {
                                pos += 9;
                            }
                        }
                    }

                    if (buff.toString('ascii', pos, pos + 4) == 'Xing' && (buff.readUInt32BE(pos + 4) & 0x0001) == 0x0001) {
                        let totalFrames = buff.readUInt32BE(pos + 8);
                        duration = totalFrames * samples / samprate;
                        break;
                    }
                }

                if (fsize < 1) break;

                pos = start + fsize;

                duration += (samples / samprate);
            }
        }

        return { duration: ~~duration };
    },

    EBML: (buff) => {
        let width = null, height = null, duration = null;
        let pos = 0;
        let timecodeScale = 1000000; // Default: 1ms
        let durationValue = null;

        // Helper to read VINT (variable-length integer)
        // For element IDs, keepMarker should be true
        // For sizes, keepMarker should be false (removes the size marker)
        const readVINT = (pos, keepMarker = false) => {
            if (pos >= buff.length) return { value: 0, size: 0 };

            let firstByte = buff[pos];
            let mask = 0x80;
            let size = 1;

            // Find the size by looking for the first 1 bit
            while (size <= 8 && !(firstByte & mask)) {
                mask >>= 1;
                size++;
            }

            if (size > 8 || pos + size > buff.length) {
                return { value: 0, size: 0 };
            }

            // Read the value
            let value = keepMarker ? firstByte : (firstByte & (mask - 1));
            for (let i = 1; i < size; i++) {
                value = (value << 8) | buff[pos + i];
            }

            return { value, size };
        };

        // Helper to read element ID (keeps marker bit)
        const readElementID = (pos) => {
            return readVINT(pos, true);
        };

        // Helper to read element size (removes marker bit)
        const readElementSize = (pos) => {
            return readVINT(pos, false);
        };

        // Helper to read unsigned integer
        const readUInt = (pos, size) => {
            if (pos + size > buff.length) return 0;
            let value = 0;
            for (let i = 0; i < size; i++) {
                value = (value << 8) | buff[pos + i];
            }
            return value;
        };

        // Helper to read float
        const readFloat = (pos, size) => {
            if (pos + size > buff.length) return 0;
            if (size === 4) {
                return buff.readFloatBE(pos);
            } else if (size === 8) {
                return buff.readDoubleBE(pos);
            }
            return 0;
        };

        const maxIterations = 1000;
        let iterations = 0;

        // Parse EBML elements
        while (pos < buff.length && iterations++ < maxIterations) {
            const idResult = readElementID(pos);
            if (idResult.size === 0) break;

            pos += idResult.size;

            const sizeResult = readElementSize(pos);
            if (sizeResult.size === 0) break;

            pos += sizeResult.size;

            const elementID = idResult.value;
            const elementSize = sizeResult.value;
            const dataStart = pos;

            // Check for specific elements we care about

            // TimecodeScale (0x2AD7B1) - in SegmentInfo
            if (elementID === 0x2AD7B1) {
                timecodeScale = readUInt(dataStart, elementSize);
            }

            // Duration (0x4489) - in SegmentInfo
            if (elementID === 0x4489) {
                durationValue = readFloat(dataStart, elementSize);
            }

            // PixelWidth (0xB0) - in Video
            if (elementID === 0xB0) {
                width = readUInt(dataStart, elementSize);
            }

            // PixelHeight (0xBA) - in Video
            if (elementID === 0xBA) {
                height = readUInt(dataStart, elementSize);
            }

            // If we found dimensions and duration, we can stop
            if (width && height && durationValue !== null) {
                break;
            }

            pos = dataStart + elementSize;
        }

        // Calculate duration in seconds
        if (durationValue !== null && timecodeScale > 0) {
            duration = ~~(durationValue * timecodeScale / 1000000000);
        }

        return { width, height, duration };
    }

};

// Worker thread execution
try {
    const { type, buffer } = workerData;
    const buff = Buffer.from(buffer);

    if (parser[type]) {
        const result = parser[type](buff);
        parentPort.postMessage(result);
    } else {
        parentPort.postMessage({});
    }
} catch (error) {
    throw error;
}
