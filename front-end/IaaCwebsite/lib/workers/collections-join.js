const { parentPort, workerData } = require('worker_threads');

/**
 * Perform collection join in a worker thread
 * This handles the CPU-intensive nested loop operations
 */
function joinCollections(collection1, collection2, matches, matchAll) {
    let output = [];

    for (let row1 of collection1) {
        let newRow = clone(row1);

        for (let row2 of collection2) {
            let join = false;

            for (let match in matches) {
                if (row1[match] == row2[matches[match]]) {
                    join = true;
                    if (!matchAll) break;
                } else if (matchAll) {
                    join = false;
                    break;
                }
            }

            if (join) {
                for (let column in row2) {
                    newRow[column] = clone(row2[column]);
                }
                break;
            }
        }

        output.push(newRow);
    }

    return output;
}

function clone(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    if (obj instanceof Date) return new Date(obj.getTime());
    if (obj instanceof Array) return obj.map(item => clone(item));
    if (obj instanceof Object) {
        const clonedObj = {};
        for (let key in obj) {
            if (obj.hasOwnProperty(key)) {
                clonedObj[key] = clone(obj[key]);
            }
        }
        return clonedObj;
    }
}

// Worker thread execution
try {
    const { collection1, collection2, matches, matchAll } = workerData;
    const result = joinCollections(collection1, collection2, matches, matchAll);
    parentPort.postMessage(result);
} catch (error) {
    throw error;
}
