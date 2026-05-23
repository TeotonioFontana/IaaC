if (process.env.NODE_ENV !== 'production') {
    require('dotenv').config();
}

const server = require('./lib/server');
const config = require('./lib/setup/config');
const debug = require('debug')('server-connect:start');

const port = config.port || 3000;
const httpsOptions = config.https && config.https.enabled ? config.https.options : null;

if (httpsOptions) {
  // Load SSL files
  const fs = require('fs');
  if (httpsOptions.key) {
    httpsOptions.key = fs.readFileSync(__dirname + '/certs/' + httpsOptions.key);
  }
  if (httpsOptions.cert) {
    httpsOptions.cert = fs.readFileSync(__dirname + '/certs/' + httpsOptions.cert);
  }
  if (httpsOptions.ca) {
    httpsOptions.ca = fs.readFileSync(httpsOptions.ca);
  }
}

if (config.cluster) {
  debug('Starting in cluster mode');

  const cluster = require('cluster');
  const totalCPUs = require('os').cpus().length;

  if (cluster.isMaster) {
      debug(`Number of CPUs is ${totalCPUs}`);
      debug(`Master ${process.pid} is running`);

      for (let i = 0; i < totalCPUs; i++) {
          cluster.fork();
      }

      cluster.on('exit', (worker, code, signal) => {
          debug(`worker ${worker.process.pid} died`);
          debug('Starting another worker');
          cluster.fork();
      });
  } else {
      debug(`Worker ${process.pid} started`);
      server.start({ port, httpsOptions });
  }

  return;
}

server.start({ port, httpsOptions });