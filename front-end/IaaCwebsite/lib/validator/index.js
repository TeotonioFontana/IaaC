module.exports = {

    async init(app, meta) {
        const errors = {};

        for (const field in meta) {
            if (Array.isArray(meta[field])) {
                await this.validateFields(app, meta[field], app.scope.data[field], errors);
            }
        }

        if (Object.keys(errors).length) {
            app.res.status(400).json(errors);
        }
    },

    async validateData(app, data, noError) {
        const errors = {};

        if (Array.isArray(data)) {
            for (let item of data) {
                for (let rule in item.rules) {
                    const options = item.rules[rule];

                    rule = this.getRule(rule);

                    if (!await this.validateRule(app, rule, item.value, options)) {
                        const t = item.fieldName ? 'form' : 'data';
                        errors[t] = errors[t] || {};
                        errors[t][item.fieldName || item.name] = this.errorMessage(rule, options);
                    }
                }
            }
        }

        if (Object.keys(errors).length) {
            if (noError) return false;
            app.res.status(400).json(errors);
        }

        return true;
    },

    async validateFields(app, fields, parent, errors, fieldname) {
        if (parent == null) return;

        for (let field of fields) {
            let value = parent[field.name];
            let curFieldname = fieldname ? `${fieldname}[${field.name}]` : field.name;

            if (field.type == 'array' && value == null) {
                value = [];
            }

            if (field.options && field.options.rules) {
                await this.validateField(app, field, value, errors, curFieldname);
            }

            if (field.type == 'object' && field.sub) {
                await this.validateFields(app, field.sub, value, errors, curFieldname);
            }

            if (field.type == 'array' && field.sub && field.sub[0] && field.sub[0].sub) {
                if (Array.isArray(value) && value.length) {
                    for (let i = 0; i < value.length; i++) {
                        await this.validateFields(app, field.sub[0].sub, value[i], errors, `${curFieldname}[${i}]`);
                    }
                } else {
                    await this.validateFields(app, field.sub[0].sub, null, errors, `${curFieldname}[0]`);
                }
            }
        }
    },

    async validateField(app, field, value, errors, fieldname) {
        const required = field.options.rules['core:required'];
        const t = field.fieldName ? 'form' : 'data';

        if (required && !value) {
            errors[t] = errors[t] || {};
            errors[t][fieldname] = this.errorMessage({ module: 'core', method: 'required' }, required);
            return
        }

        for (let rule in field.options.rules) {
            if (rule == 'core:required') continue;

            const options = field.options.rules[rule];

            rule = this.getRule(rule);

            if (!await this.validateRule(app, rule, value, options)) {
                errors[t] = errors[t] || {};
                errors[t][fieldname] = this.errorMessage(rule, options);
                return;
            }
        }
    },

    async validateRule(app, rule, value, options = {}) {
        const module = require(`./${rule.module}`);
        return module[rule.method].call(app, value, options.param);
    },

    errorMessage(rule, options = {}) {
        let message = options.message;

        if (!message) {
            const { validator: messages } = require('../locale/en-US');
            message = messages[rule.module][rule.method];
        }

        if (typeof options.param != 'object') {
            options.param = { '0': options.param };
        }

        return message.replace(/{([^}]+)}/g, (m, i) => options.param[i]);
    },

    getRule(rule) {
        const colon = rule.indexOf(':');

        return {
            module: colon > 0 ? rule.substr(0, colon) : 'core',
            method: colon > 0 ? rule.substr(colon + 1) : rule
        };
    }

};