const fs = require('fs-extra');
const { resolve } = require('path');

module.exports = function(app) {
    app.all('/webhooks/:name', (req, res, next) => {
        const name = req.params.name;

        if (!/^[a-zA-Z0-9-_]+$/.test(name)) {
            res.status(400).json({error: `Invalid webhook name.`});
        } else if (fs.existsSync(`lib/webhooks/${name}.js`)) {
            // Use absolute path for require to handle CWD changes
            const webhook = require(resolve(`lib/webhooks/${name}.js`));
            if (webhook.handler) {
                webhook.handler(req, res, next);
            } else {
                res.status(400).json({error: `Webhook ${name} has no handler.`});
            }
        } else {
            const webhook = require('../core/webhook');
            const handler = webhook.createHandler(name);
            handler(req, res, next);
        }
    });
};