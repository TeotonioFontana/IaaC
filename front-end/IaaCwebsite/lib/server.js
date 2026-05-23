process.on('uncaughtException', (e) => {
    // prevent errors from killing the server and just log them
    console.error(e);
});

const debug = require('debug');
debug.log = console.log.bind(console);

const config = require('./setup/config');
const secure = require('./setup/secure');
const routes = require('./setup/routes');
const sockets = require('./setup/sockets');
const upload = require('./setup/upload');
const cron = require('./setup/cron');
const auth = require('./setup/auth');
const express = require('express');
const endmw = require('express-end');
const cookieParser = require('cookie-parser');
const session = require('./setup/session'); //require('express-session')(Object.assign({ secret: config.secret }, config.session));
const cors = require('cors');
const app = express();

app.set('trust proxy', true);
app.set('view engine', 'ejs');
app.set('view options', { root: 'views', async: true });

app.set('json replacer', (key, value) => {
    if (value instanceof Set) return [...value];
    if (value instanceof Error) return value.toString();
    return value;
});

app.disable('x-powered-by')

if (config.compression) {
    const compression = require('compression');
    app.use(compression());
}

if (config.abortOnDisconnect) {
    app.use((req, res, next) => {
        req.isDisconnected = false;
        req.on('close', () => {
            req.isDisconnected = true;
        });

        next();
    });
}

app.use(cors(config.cors));
app.use(express.static('public', config.static));
app.use(express.urlencoded({ extended: true }));
app.use(express.json({
    verify: (req, res, buf) => {
        req.rawBody = buf.toString()
    }
}));
app.use(cookieParser(config.secret));
app.use(session);
app.use(endmw);

upload(app);
secure(app);
routes(app);
auth(app); // new auth system

module.exports = {
    start: function({ port, httpsOptions } = {}) {
        const server = httpsOptions ? require('https').createServer(httpsOptions, app) : require('http').createServer(app);
        const io = sockets(server, session);

        // Make sockets global available
        global.io = io;

        // We add the 404 and 500 routes as last
        app.use((req, res) => {
            // if user has a custom 404 page, redirect to it
            if (req.accepts('html') && req.url != '/404' && app.get('has404')) {
                //res.redirect(303, '/404');
                res.status(404);
                req.url = '/404';
                app.handle(req, res);
            } else {
                res.status(404).json({
                    status: '404',
                    message: `${req.url} not found.`
                });
            }
        });

        app.use((err, req, res, next) => {
            console.error(err);
            // if user has a custom 500 page, redirect to it
            if (req.accepts('html') && req.url != '/500' && app.get('has500')) {
                //res.redirect(303, '/500');
                res.status(500);
                req.url = '/500';
                app.handle(req, res);
            } else {
                res.status(500).json({
                    status: '500',
                    code: config.debug ? err.code : undefined,
                    message: config.debug ? err.message || err : 'A server error occured, to see the error enable the DEBUG flag.',
                    stack: config.debug ? err.stack : undefined,
                });
            }
        });

        cron.start();

        if (!port) port = config.port || 3000;

        server.listen(port, () => {
            let url = `http${httpsOptions ? 's' : ''}://localhost:${port}`;
            if (process.env.WAPPLER_SERVER_HTTPS_URL) {
                url = process.env.WAPPLER_SERVER_HTTPS_URL;
            }
            console.log(`App listening at ${url}`);
        });
    }
};
