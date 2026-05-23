const package = require('../../package.json');
const fs = require('fs-extra');
const debug = require('debug')('server-connect:setup:config');
const { toSystemPath } = require('../core/path');
const { mergeDeep } = require('../core/util');
const Parser = require('../core/parser');
const Scope = require('../core/scope');

const setIfEnv = (configObj, configKey, envKey, transform = (val) => val) => {
    if (process.env[envKey]) {
        configObj[configKey] = transform(process.env[envKey]);
    }
}

const config = {
    port: process.env.PORT || 3000,
    debug: false,
    debugOutputAll: false,
    secret: process.env.SECRET || 'Need to be set',
    tmpFolder: '/tmp',
    abortOnDisconnect: false,
    createApiRoutes: true,
    compression: true,
    redis: false,
    cron: true,
    https: {
        enabled: false,
        options: {
            key: null,
            cert: null,
            ca:  null,
        },
    },
    static: {
        index: false,
    },
    session: {
        name: package.name + '.sid',
        resave: false,
        saveUninitialized: false,
        store: {
            $type: 'memory',
            ttl: 86400
        },
    },
    cors: { // see https://github.com/expressjs/cors
        origin: false,
        methods: 'GET,POST',
        credentials: true,
    },
    csrf: {
        enabled: false,
        exclude: 'GET,HEAD,OPTIONS',
    },
    rateLimit: {
        enabled: false,
        duration: 60, // duration of 60 second (1 minute)
        points: 100, // limit to 100 requests per minute
        private: {
            provider: '', // security provider name
            duration: 60, // duration of 60 second (1 minute)
            points: 1000, // limit to 1000 requests per minute
        },
    },
    helmet: {
        enabled: false,
        // Stripe recommended security settings
        // https://docs.stripe.com/security/guide?csp=csp-js
        // More urls needed for App Connnect components?
        // Do we need stripe urls in the default config, most users don't use it?
        contentSecurityPolicy: {
            directives: {
                baseUri: ["'self'"],
                defaultSrc: ["'self'"],
                fontSrc: ["'self'", "https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://use.fontawesome.com"],
                imgSrc: ["'self'", "data:", "https://*.stripe.com"],
                scriptSrc: ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://code.jquery.com", "https://*.js.stripe.com", "https://js.stripe.com", "https://maps.googleapis.com"],
                styleSrc: ["'self'", "'unsafe-inline'", "https://use.fontawesome.com", "https://cdn.jsdelivr.net"], // https://stackpath.bootstrapcdn.com (Fontawesome 4.7 CSS)
                frameSrc: ["'self'", "https://js.stripe.com", "https://hooks.stripe.com", "https://*.js.stripe.com"],
                connectSrc: ["'self'", "https://api.stripe.com", "https://maps.googleapis.com"],
            },
        },
        crossOriginOpenerPolicy: {
            policy: "same-origin",
        },
        crossOriginResourcePolicy: {
            policy: "same-origin",
        },
        referrerPolicy: {
            policy: "no-referrer",
        },
        strictTransportSecurity: false,
        xContentTypeOptions: true,
        xDnsPrefetchControl: false,
        xFrameOptions: false,
    },
    cluster: false,
    globals: {},
    rateLimiter: {},
    mail: {},
    auth: {},
    oauth: {},
    db: {},
    s3: {},
    jwt: {},
    stripe: {},
    env: {},
};

if (fs.existsSync('app/config/config.json')) {
    mergeDeep(config, fs.readJSONSync('app/config/config.json'))
}

if (fs.existsSync('app/config/user_config.json')) {
    mergeDeep(config, fs.readJSONSync('app/config/user_config.json'));
}

// folders are site relative
config.tmpFolder = toSystemPath(config.tmpFolder);

if (config.env) {
    for (let key in config.env) {
        if (!Object.hasOwn(process.env, key)) {
            process.env[key] = config.env[key];
        } else if (config.debug) {
            debug(`"${key}" is already defined in \`process.env\` and will not be overwritten`);
        }
    }
}

Parser.parseValue(config, new Scope({
    $_ENV: process.env
}));

setIfEnv(config, 'port', 'WAPPLER_SERVER_PORT', Number);
setIfEnv(config, 'debug', 'WAPPLER_SERVER_DEBUG');
setIfEnv(config, 'debugOutputAll', 'WAPPLER_SERVER_DEBUG_OUTPUT_ALL', val => !!val);
setIfEnv(config, 'secret', 'WAPPLER_SERVER_SECRET');
setIfEnv(config, 'redis', 'WAPPLER_SERVER_REDIS_URL', val => val === 'true' ? true : val);
setIfEnv(config.https, 'enabled', 'WAPPLER_SERVER_HTTPS', val => val === 'true');
setIfEnv(config.https.options, 'key', 'WAPPLER_SERVER_HTTPS_KEY');
setIfEnv(config.https.options, 'cert', 'WAPPLER_SERVER_HTTPS_CERT');
setIfEnv(config.https.options, 'ca', 'WAPPLER_SERVER_HTTPS_CA');
setIfEnv(config.session.store, '$type', 'WAPPLER_SERVER_SESSION_STORE_TYPE');
setIfEnv(config.session.store, 'ttl', 'WAPPLER_SERVER_SESSION_TTL', Number);
setIfEnv(config.cors, 'origin', 'WAPPLER_SERVER_CORS_ORIGIN');
setIfEnv(config.cors, 'methods', 'WAPPLER_SERVER_CORS_METHODS');
setIfEnv(config.cors, 'credentials', 'WAPPLER_SERVER_CORS_CREDENTIALS', val => val === 'true');
setIfEnv(config.csrf, 'enabled', 'WAPPLER_SERVER_CSRF', val => val === 'true');
setIfEnv(config.csrf, 'exclude', 'WAPPLER_SERVER_CSRF_EXCLUDE');
setIfEnv(config.rateLimit, 'enabled', 'WAPPLER_SERVER_RATELIMIT', val => val === 'true');
setIfEnv(config.rateLimit, 'duration', 'WAPPLER_SERVER_RATELIMIT_DURATION', Number);
setIfEnv(config.rateLimit, 'points', 'WAPPLER_SERVER_RATELIMIT_POINTS', Number);
setIfEnv(config.rateLimit.private, 'provider', 'WAPPLER_SERVER_RATELIMIT_PRIVATE_PROVIDER');
setIfEnv(config.rateLimit.private, 'duration', 'WAPPLER_SERVER_RATELIMIT_PRIVATE_DURATION', Number);
setIfEnv(config.rateLimit.private, 'points', 'WAPPLER_SERVER_RATELIMIT_PRIVATE_POINTS', Number);
setIfEnv(config, 'cluster', 'WAPPLER_SERVER_CLUSTER', val => val === 'true');

// we change the cors config a bit, * will become true
// and we split string on comma for multiple origins
if (typeof config.cors?.origin == 'string') {
    if (config.cors.origin === '*') {
        config.cors.origin = true;
    } else if (config.cors.origin.includes(',')) {
        config.cors.origin = config.cors.origin.split(/\s*,\s*/);
    }
}

if (config.debug) {
    require('debug').enable(typeof config.debug == 'string' ? config.debug : 'server-connect:*');
}

if (config.redis) {
    const Redis = require('ioredis');
    global.redisClient = new Redis(config.redis === true ? 'redis://redis' : config.redis);
}

debug(config);

module.exports = config;