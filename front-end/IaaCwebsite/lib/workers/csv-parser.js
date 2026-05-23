const { parentPort, workerData } = require('worker_threads');

/**
 * Parse CSV data in a worker thread
 */
function parseCSV(csv, options) {
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

// Worker thread execution
try {
    const { csv, options } = workerData;
    const result = parseCSV(csv, options);
    parentPort.postMessage(result);
} catch (error) {
    throw error;
}
