const { parentPort, workerData } = require('worker_threads');

/**
 * Export data to CSV format in a worker thread
 */
function exportCSV(data, delimiter, header) {
    let output = '';

    if (header) {
        output += putcsv(Object.keys(data[0]), delimiter);
    }

    for (let row of data) {
        output += putcsv(row, delimiter);
    }

    return output;
}

function putcsv(data, delimiter) {
    let str = '';

    if (typeof data != 'object') {
        throw new Error('putcsv: Invalid data.');
    }

    for (let prop in data) {
        if (Object.hasOwn(data, prop)) {
            let value = String(data[prop]);

            if (/["\n\r\t\s]/.test(value) || value.includes(delimiter)) {
                let escaped = false;
                
                str += '"';

                for (let i = 0; i < value.length; i++) {
                    if (value.charAt(i) == '\\') {
                        escaped = true;
                    } else if (!escaped && value.charAt(i) == '"') {
                        str += '"';
                    } else {
                        escaped = false;
                    }

                    str += value.charAt(i);
                }

                str += '"';
            } else {
                str += value;
            }

            str += delimiter;
        }
    }

    if (!str) {
        throw new Error('putcsv: No data.');
    }

    return str.substr(0, str.length - delimiter.length) + '\r\n';
}

// Worker thread execution
try {
    const { data, delimiter, header } = workerData;
    const result = exportCSV(data, delimiter, header);
    parentPort.postMessage(result);
} catch (error) {
    throw error;
}
