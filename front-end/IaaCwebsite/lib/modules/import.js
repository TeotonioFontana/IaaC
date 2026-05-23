const fs = require('fs-extra');
const { join } = require('path');
const { toSystemPath } = require('../core/path');
const { keysToLowerCase } = require('../core/util');
const { runWorker } = require('../core/worker');

// Threshold for using worker thread (100KB)
const WORKER_THRESHOLD = 100 * 1024;

module.exports = {

    csv: async function(options) {
        let path = this.parseRequired(options.path, 'string', 'import.csv: path is required.');
        let fields = this.parseOptional(options.fields, 'object', []);
        let header = this.parseOptional(options.header, 'boolean', false);
        let delimiter = this.parseOptional(options.delimiter, 'string', ',');
        let csv = await fs.readFile(toSystemPath(path), 'utf8');

        // Use worker thread for large CSV files to prevent blocking
        if (csv.length > WORKER_THRESHOLD) {
            const workerFile = join(__dirname, '..', 'workers', 'csv-parser.js');
            return runWorker(workerFile, { csv, options: { fields, header, delimiter, path } });
        }

        // For small files, parse inline (faster than worker overhead)
        return parseCSVInline(csv, { fields, header, delimiter, path });
    },

    xml: async function(options) {
        // TODO: import.xml
        throw new Error('import.xml: not implemented.');
    },

};

// Inline CSV parser for small files (avoids worker thread overhead)
function parseCSVInline(csv, options) {
    if (!csv) return [];

    if (csv.charCodeAt(0) === 0xFEFF) {
        csv = csv.slice(1);
    }

    let delimiter = options.delimiter.replace('\\t', '\t');
    let keys = options.fields;
    let line = 1;
    let data = [];

    if (options.header) {
        keys = getcsv();

        options.fields.forEach(field => {
            if (keys.indexOf(field) == -1) {
                throw new Error('parseCSV: ' + field + ' is missing in ' + options.path);
            }
        });

        line++;
    }

    let size = keys.length;

    while (csv.length) {
        let values = getcsv();
        let o = {};

        if (values.length != size) {
            throw new Error('parseCSV: columns do not match. keys: ' + size + ', values: ' + values.length + ' at line ' + line);
        }

        for (let i = 0; i < size; i++) {
            o[keys[i]] = values[i];
        }

        data.push(o);

        line++;
    }

    return data;

    function getcsv() {
        let data = [''], l = csv.length,
            esc = false, escesc = false,
            n = 0, i = 0;

        while (i < l) {
            let s = csv.charAt(i);

            if (s == '\n') {
                if (esc) {
                    data[n] += s;
                } else {
                    i++;
                    break;
                }
            } else if (s == '\r') {
                if (esc) {
                    data[n] += s;
                }
            } else if (s == delimiter) {
                if (esc) {
                    data[n] += s;
                } else {
                    data[++n] = '';
                    esc = false;
                    escesc = false;
                }
            } else if (s == '"') {
                if (escesc) {
                    data[n] += s;
                    escesc = false;
                }

                if (esc) {
                    esc = false;
                    escesc = true;
                } else {
                    esc = true;
                    escesc = false;
                }
            } else {
                if (escesc) {
                    data[n] += '"';
                    escesc = false;
                }

                data[n] += s;
            }

            i++;
        }

        csv = csv.substr(i);

        return data;
    }
}
