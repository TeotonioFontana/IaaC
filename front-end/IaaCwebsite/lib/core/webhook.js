// Helper methods for webhooks

const fs = require('fs-extra');
const path = require('path');
const App = require('./app');

/**
 * Validates and sanitizes action names to prevent path traversal attacks
 * @param {string} action - The action name to validate
 * @returns {string|null} - Sanitized action name or null if invalid
 */
function sanitizeActionName(action) {
    if (!action || typeof action !== 'string') {
        return null;
    }

    // Trim whitespace
    action = action.trim();

    if (!action) {
        return null;
    }

    // Reject any path with dangerous characters or patterns
    // This prevents:
    // - Path traversal: .. sequences
    // - Directory separators: / or \
    // - Drive letters: C: etc
    // - Special chars that could be dangerous: null bytes, etc
    // - Hidden files: starting with .
    if (
        action.includes('..') ||
        action.includes('/') ||
        action.includes('\\') ||
        action.includes('\x00') || // null byte
        action.includes(':') ||     // drive letters or alternate streams
        action.startsWith('.')      // hidden files (but allow dots elsewhere for Stripe events like "payment_intent.succeeded")
    ) {
        return null;
    }

    // Allow alphanumeric, hyphens, underscores, and dots (for Stripe events like "payment_intent.succeeded")
    // Dots are safe when not at the start and when .. is already blocked above
    if (!/^[a-zA-Z0-9_.-]+$/.test(action)) {
        return null;
    }

    return action;
}

exports.createHandler = function(name, fn = () => 'handler') {
    return async (req, res, next) => {
        try {
            const action = await fn(req, res, next);

            if (typeof action == 'string') {
                // Sanitize action name to prevent path traversal
                const sanitizedAction = sanitizeActionName(action);

                if (!sanitizedAction) {
                    return res.status(400).json({
                        error: `Invalid action name: "${action}". Only alphanumeric characters, hyphens, underscores, and dots are allowed.`
                    });
                }

                // Construct path safely using path.join to normalize
                const webhookDir = path.join('app', 'webhooks', name);
                const actionPath = path.join(webhookDir, `${sanitizedAction}.json`);

                // Verify the resolved path is still within the webhook directory
                // This prevents traversal even if sanitization is bypassed somehow
                const resolvedPath = path.resolve(actionPath);
                const resolvedWebhookDir = path.resolve(webhookDir);

                if (!resolvedPath.startsWith(resolvedWebhookDir)) {
                    return res.status(400).json({
                        error: 'Invalid action path.'
                    });
                }

                if (fs.existsSync(actionPath)) {
                    const app = new App(req, res);
                    let json = await fs.readJSON(actionPath);
                    return Promise.resolve(app.define(json)).catch(next);
                } else {
                    res.json({error: `No action found for ${sanitizedAction}.`});
                    // do not return 404 else stripe will retry
                    //next();
                }
            }
        } catch (err) {
            // Handle errors in webhook function
            next(err);
        }
    }
};