const config = require('./config');

if (config.redis) {
    const Redis = require('ioredis');
    const debug = require('debug')('redis');

    global.redisClient = new Redis(config.redis === true ? 'redis://redis' : config.redis, {
        retryStrategy: function(times) {
            var delay = Math.min(times * 50, 2000);
            return delay;
        },

        reconnectOnError: function(err) {
            if (err.message.includes('READONLY')) {
                return true;
            }
            if (err.message.includes('ECONNRESET')) {
                return true;
            }
            return false;
        }
    });

    
    global.redisClient.on('connect', () => {
        debug('Redis connected successfully.');
    });

    global.redisClient.on('ready', () => {
        debug('Redis is ready to use.');
    });

    global.redisClient.on('error', (err) => {
        debug('Got a Redis error');
        console.error(err);
    });

    global.redisClient.on('reconnecting', (delay) => {
        debug(`Reconnecting to Redis in ${delay}ms...`);
    });

    global.redisClient.on('end', () => {
        debug('Redis connection has been closed.');
    });
}

module.exports = global.redisClient;