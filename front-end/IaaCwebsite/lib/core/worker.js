const { Worker } = require('worker_threads');
const { join } = require('path');
const debug = require('debug')('server-connect:worker');

/**
 * Run a function in a worker thread
 * @param {string} workerFile - Path to the worker file
 * @param {*} data - Data to pass to the worker
 * @param {object} options - Worker options
 * @param {number} options.timeout - Timeout in milliseconds (default: 30000)
 * @returns {Promise} Result from worker
 */
function runWorker(workerFile, data, options = {}) {
    const timeout = options.timeout || 30000;

    return new Promise((resolve, reject) => {
        const worker = new Worker(workerFile, {
            workerData: data
        });

        let timeoutId;
        let completed = false;

        if (timeout > 0) {
            timeoutId = setTimeout(() => {
                if (!completed) {
                    completed = true;
                    worker.terminate();
                    reject(new Error(`Worker timeout after ${timeout}ms`));
                }
            }, timeout);
        }

        worker.on('message', (result) => {
            if (!completed) {
                completed = true;
                if (timeoutId) clearTimeout(timeoutId);
                resolve(result);
            }
        });

        worker.on('error', (error) => {
            if (!completed) {
                completed = true;
                if (timeoutId) clearTimeout(timeoutId);
                debug('Worker error: %O', error);
                reject(error);
            }
        });

        worker.on('exit', (code) => {
            if (!completed) {
                completed = true;
                if (timeoutId) clearTimeout(timeoutId);
                if (code !== 0) {
                    reject(new Error(`Worker stopped with exit code ${code}`));
                }
            }
        });
    });
}

module.exports = {
    runWorker
};
