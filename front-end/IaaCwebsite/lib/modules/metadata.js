const fs = require('fs-extra');
const { join } = require('path');
const { runWorker } = require('../core/worker');

const imageTypes = ['PNG', 'GIF', 'BMP', 'JPEG', 'TIFF'];
const videoTypes = ['AVI', 'MP4', 'MOV', 'MKV', 'WEBM', 'OGV', 'EBML'];  // EBML is fallback for unrecognized EBML files
const soundTypes = ['OGG', 'WAV', 'MP3', 'FLAC'];

// File types that need worker thread due to complex parsing
const WORKER_TYPES = ['JPEG', 'TIFF', 'MP4', 'MOV', 'MKV', 'WEBM', 'EBML', 'OGG', 'OGV', 'MP3'];

const read = async (path, offset, length) => {
    const fp = await fs.open(path, 'r');
    const buff = Buffer.alloc(length);

    await fs.read(fp, buff, 0, length, offset);
    await fs.close(fp);

    return buff;
};


const parser = {

    PNG: async (path, result) => {
        const buff = await read(path, 18, 6);
        result.width = buff.readUInt16BE(0);
        result.height = buff.readUInt16BE(4);
    },

    GIF: async (path, result) => {
        const buff = await read(path, 6, 4);
        result.width = buff.readUInt16LE(0);
        result.height = buff.readUInt16LE(2);
    },

    BMP: async (path, result) => {
        const buff = await read(path, 18, 8);
        result.width = buff.readUInt32LE(0);
        result.height = buff.readUInt32LE(4);
    },

    JPEG: async (path, result) => {
        const buff = await read(path, 2, 64000);

        // Use worker thread for CPU-intensive synchronous parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'JPEG', buffer: buff });
        result.width = parsed.width;
        result.height = parsed.height;
    },

    TIFF: async (path, result) => {
        const buff = await read(path, 0, 64000);

        // Use worker thread for CPU-intensive synchronous parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'TIFF', buffer: buff });
        result.width = parsed.width;
        result.height = parsed.height;
    },

    AVI: async (path, result) => {
        const buff = await read(path, 0, 144);

        // AVI structure: RIFF header + LIST hdrl + avih chunk
        // avih chunk starts at position 32 (RIFF 12 bytes + LIST hdrl 12 bytes + avih header 8 bytes)
        // Fields within avih chunk:
        //   +0: MicroSecPerFrame (4 bytes)
        //   +16: TotalFrames (4 bytes)
        //   +32: Width (4 bytes)
        //   +36: Height (4 bytes)

        const avihStart = 32;
        result.width = buff.readUInt32LE(avihStart + 32);
        result.height = buff.readUInt32LE(avihStart + 36);

        const microSecPerFrame = buff.readUInt32LE(avihStart);
        const totalFrames = buff.readUInt32LE(avihStart + 16);

        if (microSecPerFrame > 0 && totalFrames > 0) {
            result.duration = ~~((totalFrames * microSecPerFrame) / 1000000);
        }
    },

    MP4: async (path, result) => {
        return parser.MOV(path, result);
    },

    MOV: async (path, result, pos = 0) => {
        const buff = await read(path, 0, 64000);

        // Use worker thread for CPU-intensive synchronous parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'MOV', buffer: buff });
        result.width = parsed.width;
        result.height = parsed.height;
        result.duration = parsed.duration;
    },

    WEBM: async (path, result) => {
        return parser.EBML(path, result);
    },

    MKV: async (path, result) => {
        return parser.EBML(path, result);
    },

    EBML: async (path, result) => {
        const buff = await read(path, 0, 64000);

        // Use worker thread for CPU-intensive EBML parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'EBML', buffer: buff });
        result.width = parsed.width;
        result.height = parsed.height;
        result.duration = parsed.duration;
    },

    OGV: async (path, result) => {
        return parser.OGG(path, result);
    },

    OGG: async (path, result) => {
        const buff = await read(path, 0, 64000);

        // Use worker thread for CPU-intensive synchronous parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'OGG', buffer: buff });
        result.width = parsed.width;
        result.height = parsed.height;
        result.duration = parsed.duration;
    },

    WAV: async (path, result) => {
        const buff = await read(path, 0, 32);
        let size = buff.readUInt32LE(4);
        let rate = buff.readUInt32LE(28);
        result.duration = ~~(size / rate);
    },

    MP3: async (path, result) => {
        const buff = await read(path, 0, 64000);

        // Use worker thread for CPU-intensive synchronous parsing
        const workerFile = join(__dirname, '..', 'workers', 'metadata-parser.js');
        const parsed = await runWorker(workerFile, { type: 'MP3', buffer: buff });
        result.duration = parsed.duration;
    },

    FLAC: async (path, result) => {
        const buff = await read(path, 18, 8);
        let rate = (buff[0] << 12) | (buff[1] << 4) | ((buff[2] & 0xf0) >> 4);
        let size = ((buff[3] & 0x0f) << 32) | (buff[4] << 24) | (buff[5] << 16) | (buff[6] << 8) | buff[7];
        result.duration = ~~(size / rate);
    },

};

async function detect(path) {
    const buff = await read(path, 0, 64);

    if (buff.slice(0, 8).compare(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) === 0) {
        return 'PNG';
    }

    if (buff.toString('ascii', 0, 3) == 'GIF') {
        return 'GIF';
    }

    if (buff.toString('ascii', 0, 2) == 'BM') {
        return 'BMP';
    }

    if (buff.slice(0, 2).compare(Buffer.from([0xff, 0xd8])) === 0) {
        return 'JPEG';
    }

    if (buff.toString('ascii', 0, 2) == 'II' && buff.readUInt16LE(2) == 42) {
        return 'TIFF';
    }

    if (buff.toString('ascii', 0, 2) == 'MM' && buff.readUInt16BE(2) == 42) {
        return 'TIFF';
    }

    if (buff.toString('ascii', 0, 4) == 'RIFF' && buff.toString('ascii', 8, 12) == 'AVI ') {
        return 'AVI';
    }

    if (buff.toString('ascii', 4, 8) == 'ftyp') {
        return 'MP4';
    }

    if (buff.toString('ascii', 4, 8) == 'moov') {
        return 'MOV';
    }

    if (buff.slice(0, 4).compare(Buffer.from([0x1a, 0x45, 0xdf, 0xa3])) === 0) {
        // EBML format - check DocType to distinguish MKV from WEBM
        // DocType element (0x4282) contains "matroska" or "webm"
        const docTypeMatch = buff.toString('ascii', 0, 64).match(/matroska|webm/);
        if (docTypeMatch) {
            return docTypeMatch[0] === 'webm' ? 'WEBM' : 'MKV';
        }
        return 'EBML'; // Fallback if DocType not found
    }

    if (buff.toString('ascii', 0, 4) == 'OggS') {
        // Check for Theora video codec marker to distinguish OGV from OGG audio
        // Theora identification header starts with "\x80theora" after OggS page
        // Search for 'theora' string in the buffer
        for (let i = 0; i < Math.min(buff.length - 6, 64); i++) {
            if (buff[i] === 0x80 &&
                buff.toString('ascii', i + 1, i + 7) === 'theora') {
                return 'OGV';
            }
        }
        return 'OGG'; // Default to audio if no video codec detected
    }

    if (buff.toString('ascii', 0, 4) == 'RIFF' && buff.toString('ascii', 8, 12) == 'WAVE') {
        return 'WAV';
    }

    if (buff.toString('ascii', 0, 3) == 'ID3' || (buff[0] == 0xff && (buff[1] & 0xe0))) {
        return 'MP3';
    }

    if (buff.toString('ascii', 0, 4) == 'fLaC') {
        return 'FLAC';
    }

    return null
}

module.exports = {

    detect: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'metadata.detect: path is required.');

        return detect(path);
    },

    isImage: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'metadata.isImage: path is required.');
        let type = await detect(path);
        let cond = imageTypes.includes(type);

        if (cond) {
            if (options.then) {
                await this.exec(options.then, true);
            }
        } else if (options.else) {
            await this.exec(options.else, true);
        }

        return cond;
    },

    isVideo: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'metadata.isVideo: path is required.');
        let type = await detect(path);
        let cond = videoTypes.includes(type);

        if (cond) {
            if (options.then) {
                await this.exec(options.then, true);
            }
        } else if (options.else) {
            await this.exec(options.else, true);
        }

        return cond;
    },

    isSound: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'metadata.isSound: path is required.');
        let type = await detect(path);
        let cond = soundTypes.includes(type);

        if (cond) {
            if (options.then) {
                await this.exec(options.then, true);
            }
        } else if (options.else) {
            await this.exec(options.else, true);
        }

        return cond;
    },

    fileinfo: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'metadata.fileinfo: path is required.');
        let type = await detect(path);
        let result = { type, width: null, height: null, duration: null };

        if (parser[type]) {
            await parser[type](path, result);
        }

        return result;
    },

};