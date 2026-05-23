// TODO:
// - Implement WebAuthn endpoints
// - Add multi-factor authentication (MFA) support
// - Implement OAuth2 social logins (Google, Facebook, etc.)
// - Implement password reset functionality
// - Update code to use session/cookie-based auth
// - Add logging for security events
// - Implement CSRF protection for state-changing endpoints
// - Session management (view active sessions, revoke sessions)
// - Implement account deletion endpoint
// - Add support for user profile updates
// - Implement admin endpoints for user management
// - Add localization support for error messages
// - Implement audit logging for critical actions
// - Add support for CAPTCHA on registration/login
// - Implement email templates for verification and notifications
// - Add support for user roles and permissions management
// - Implement account linking for social logins
// - Implement rate limiting based on user ID in addition to IP
// - Add support for login via email (passwordless)
// - Implement account recovery options (security questions, backup codes)

const config = require('./config');

module.exports = function(app) {
  if (config.auth && config.auth.enabled) {
    setupAuthRoutes(app);
  }
};

function setupAuthRoutes(app) {
  const express = require('express');
  const rateLimit = require('express-rate-limit');
  const validator = require('validator');
  const { body, validationResult } = require('express-validator');

  const authRouter = express.Router();

  authRouter.use(helmet({
    hsts: { maxAge: 31536000, includeSubDomains: true },
    noSniff: true,
    xssFilter: true,
    frameguard: { action: 'deny' }
  }));

  // Rate limiting per endpoint
  const loginLimiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 5, // 5 attempts per window
    message: { error: 'Too many login attempts, please try again later' },
    standardHeaders: true,
    legacyHeaders: false,
    skipSuccessfulRequests: true
  });

  const registerLimiter = rateLimit({
    windowMs: 60 * 60 * 1000, // 1 hour
    max: 3, // 3 registrations per hour per IP
    message: { error: 'Too many registration attempts, please try again later' }
  });

  // Input validation middleware
  const loginValidation = [
    body('email')
      .isEmail()
      .normalizeEmail()
      .isLength({ max: 255 })
      .withMessage('Valid email is required'),
    body('password')
      .isLength({ min: 1, max: 255 })
      .withMessage('Password is required')
  ];

  const registerValidation = [
    body('email')
      .isEmail()
      .normalizeEmail()
      .isLength({ max: 255 })
      .custom(async (email) => {
        const knex = require('../core/db')(config.auth.database.connection);
        const existingUser = await knex(config.auth.database.tables.users)
          .where('email', email)
          .first();
        if (existingUser) {
          throw new Error('Email already in use');
        }
      }),
    body('password')
      .isLength({ min: config.auth.password.minLength })
      .matches(/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)/)
      .withMessage('Password must contain uppercase, lowercase, and number'),
    body('firstName')
      .optional()
      .isLength({ max: 100 })
      .trim()
      .escape(),
    body('lastName')
      .optional()
      .isLength({ max: 100 })
      .trim()
      .escape()
  ];

  // Handle login
  authRouter.post('/login', loginLimiter, loginValidation, async (req, res) => {
    try {
      // Validate input
      const errors = validationResult(req);
      if (!errors.isEmpty()) {
        return res.status(400).json({
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Invalid input data',
            details: errors.array()
          }
        });
      }

      const { email, password } = req.body;
      const knex = require('../core/db')(config.auth.database.connection);

      // Get user with account locking check
      const user = await knex(config.auth.database.tables.users)
        .where('email', email)
        .first();

      if (!user) {
        return res.status(401).json({
          success: false,
          error: {
            code: 'INVALID_CREDENTIALS',
            message: 'Invalid email or password'
          }
        });
      }

      // Check account lock
      if (user.locked_until && new Date() < user.locked_until) {
        return res.status(423).json({
          success: false,
          error: {
            code: 'ACCOUNT_LOCKED',
            message: 'Account temporarily locked due to too many failed attempts'
          }
        });
      }

      // Verify password
      const argon2 = require('argon2');
      const validPassword = await argon2.verify(user.password_hash, password);

      if (!validPassword) {
        // Increment failed attempts
        const newAttempts = user.login_attempts + 1;
        let updateData = { login_attempts: newAttempts };

        // Lock account if max attempts reached
        if (newAttempts >= config.auth.security.accountLocking.maxAttempts) {
          const lockDuration = parseDuration(config.auth.security.accountLocking.lockDuration);
          updateData.locked_until = new Date(Date.now() + lockDuration);
        }

        await knex(config.auth.database.tables.users)
          .where('id', user.id)
          .update(updateData);

        return res.status(401).json({
          success: false,
          error: {
            code: 'INVALID_CREDENTIALS',
            message: 'Invalid email or password',
            details: { attemptsRemaining: Math.max(0, config.auth.security.accountLocking.maxAttempts - newAttempts) }
          }
        });
      }

      // Check email verification if required
      if (config.auth.registration.requireEmailVerification && !user.email_verified) {
        return res.status(403).json({
          success: false,
          error: {
            code: 'EMAIL_NOT_VERIFIED',
            message: 'Please verify your email address before logging in'
          }
        });
      }

      // Reset failed attempts and update last login
      await knex(config.auth.database.tables.users)
        .where('id', user.id)
        .update({
          login_attempts: 0,
          locked_until: null,
          last_login_at: knex.fn.now()
        });

      // Generate secure tokens (server-side only)
      const accessToken = generateAccessToken(user);
      const refreshToken = generateRefreshToken(user);

      // Store refresh token securely (server-side only)
      await storeRefreshToken(user.id, refreshToken);

      // Get user roles and permissions
      const userRoles = await getUserRoles(user.id);
      const userPermissions = await getUserPermissions(user.id);

      // Return sanitized user data (no sensitive info)
      res.json({
        success: true,
        user: sanitizeUser(user),
        roles: userRoles,
        permissions: userPermissions,
        tokens: {
          accessToken: accessToken,
          refreshToken: refreshToken,
          expiresIn: getTokenExpiry(config.auth.tokens.accessTokenExpiry)
        }
      });

    } catch (error) {
      console.error('Login error:', error);
      res.status(500).json({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: 'An error occurred during login'
        }
      });
    }
  });

  // Handle registration
  authRouter.post('/register', registerLimiter, registerValidation, async(req, res) => {
    try {
      const errors = validationResult(req);
      if (!errors.isEmpty()) {
        return res.status(400).json({
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Invalid input data',
            details: errors.array()
          }
        });
      }

      // Check if registration is enabled
      if (!config.auth.registration.enabled) {
        return res.status(403).json({
          success: false,
          error: {
            code: 'REGISTRATION_DISABLED',
            message: 'User registration is currently disabled'
          }
        });
      }

      const { email, password, firstName, lastName } = req.body;
      const knex = require('../core/db')(config.auth.database.connection);

      // Hash password securely (server-side only)
      const argon2 = require('argon2');
      const passwordHash = await argon2.hash(password, {
        type: argon2.argon2id,
        memoryCost: 2 ** 16, // 64 MB
        timeCost: 3,
        parallelism: 1
      });

      // Create user
      const userData = {
        email: email,
        password_hash: passwordHash,
        first_name: firstName || null,
        last_name: lastName || null,
        email_verified: !config.auth.registration.requireEmailVerification,
        email_verification_token: config.auth.registration.requireEmailVerification ?
          require('crypto').randomBytes(32).toString('hex') : null
      };

      const [userId] = await knex(config.auth.database.tables.users)
        .insert(userData);

      // Assign default role
      if (config.auth.registration.defaultRole) {
        await knex(config.auth.database.tables.roles).insert({
          user_id: userId,
          role: config.auth.registration.defaultRole
        });
      }

      // Send verification email if required (server-side only)
      if (config.auth.registration.requireEmailVerification) {
        await sendVerificationEmail(email, userData.email_verification_token);

        return res.status(201).json({
          success: true,
          message: 'Account created successfully. Please check your email for verification instructions.',
          requiresVerification: true
        });
      }

      // Get created user
      const newUser = await knex(config.auth.database.tables.users)
        .where('id', userId)
        .first();

      // Auto-login if no verification required
      const accessToken = generateAccessToken(newUser);
      const refreshToken = generateRefreshToken(newUser);
      await storeRefreshToken(newUser.id, refreshToken);

      res.status(201).json({
        success: true,
        user: sanitizeUser(newUser),
        tokens: {
          accessToken: accessToken,
          refreshToken: refreshToken,
          expiresIn: getTokenExpiry(config.auth.tokens.accessTokenExpiry)
        }
      });

    } catch (error) {
      console.error('Registration error:', error);
      res.status(500).json({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: 'An error occurred during registration'
        }
      });
    }
  });

  // Handle token refresh
  authRouter.post('/refresh', async (req, res) => {
    try {
      const { refreshToken } = req.body;

      if (!refreshToken) {
        return res.status(401).json({
          success: false,
          error: {
            code: 'TOKEN_REQUIRED',
            message: 'Refresh token is required'
          }
        });
      }

      // Validate refresh token (server-side only)
      const tokenData = await validateRefreshToken(refreshToken);
      if (!tokenData) {
        return res.status(401).json({
          success: false,
          error: {
            code: 'INVALID_TOKEN',
            message: 'Invalid or expired refresh token'
          }
        });
      }

      // Get current user
      const knex = require('../core/db')(config.auth.database.connection);
      const user = await knex(config.auth.database.tables.users)
        .where('id', tokenData.userId)
        .first();

      if (!user) {
        return res.status(401).json({
          success: false,
          error: {
            code: 'USER_NOT_FOUND',
            message: 'User not found'
          }
        });
      }

      // Generate new tokens
      const newAccessToken = generateAccessToken(user);
      const newRefreshToken = generateRefreshToken(user);

      // Rotate refresh token
      await rotateRefreshToken(tokenData.id, newRefreshToken);

      res.json({
        success: true,
        tokens: {
          accessToken: newAccessToken,
          refreshToken: newRefreshToken,
          expiresIn: getTokenExpiry(config.auth.tokens.accessTokenExpiry)
        }
      });

    } catch (error) {
      console.error('Token refresh error:', error);
      res.status(500).json({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: 'An error occurred during token refresh'
        }
      });
    }
  });

  // Handle fetching current user info
  authRouter.get('/me', authenticateToken, async (req, res) => {
    try {
      const knex = require('../core/db')(config.auth.database.connection);

      // Get user with roles and permissions
      const user = await knex(config.auth.database.tables.users)
        .where('id', req.user.id)
        .first();

      if (!user) {
        return res.status(404).json({
          success: false,
          error: {
            code: 'USER_NOT_FOUND',
            message: 'User not found'
          }
        });
      }

      const userRoles = await getUserRoles(user.id);
      const userPermissions = await getUserPermissions(user.id);

      res.json({
        success: true,
        user: sanitizeUser(user),
        roles: userRoles,
        permissions: userPermissions
      });

    } catch (error) {
      console.error('Get profile error:', error);
      res.status(500).json({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: 'An error occurred while fetching profile'
        }
      });
    }
  });

  // Handle logout
  authRouter.post('/logout', authenticateToken, async (req, res) => {
    try {
      const { refreshToken } = req.body;

      // Invalidate refresh token if provided
      if (refreshToken) {
        await invalidateRefreshToken(refreshToken);
      }

      // Invalidate all tokens for user if requested
      if (req.body.logoutAll) {
        await invalidateAllUserTokens(req.user.id);
      }

      res.json({
        success: true,
        message: 'Logged out successfully'
      });

    } catch (error) {
      console.error('Logout error:', error);
      res.status(500).json({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: 'An error occurred during logout'
        }
      });
    }
  });

  // Handle WebAuthn registration start
  authRouter.post('/webauthn/register/begin', (req, res) => {
  });
  
  // Handle WebAuthn registration completion
  authRouter.post('/webauthn/register/complete', (req, res) => {
  });

  // Handle WebAuthn authenticate start
  authRouter.post('/webauthn/authenticate/begin', (req, res) => {
  });
  
  // Handle WebAuthn authenticate completion
  authRouter.post('/webauthn/authenticate/complete', (req, res) => {
  });

  app.use('/auth', authRouter);
}

// Server-side authentication middleware
function authenticateToken(req, res, next) {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Bearer TOKEN

  if (!token) {
    return res.status(401).json({
      success: false,
      error: {
        code: 'TOKEN_REQUIRED',
        message: 'Access token is required'
      }
    });
  }

  const jwt = require('jsonwebtoken');

  jwt.verify(token, config.auth.secret, (err, user) => {
    if (err) {
      return res.status(403).json({
        success: false,
        error: {
          code: 'TOKEN_INVALID',
          message: 'Invalid or expired access token'
        }
      });
    }

    req.user = user;
    next();
  });
}

// Server-side utility functions (no client access)
function generateAccessToken(user) {
  const jwt = require('jsonwebtoken');
  return jwt.sign(
    {
      id: user.id,
      email: user.email,
      type: 'access'
    },
    config.auth.secret,
    {
      expiresIn: config.auth.tokens.accessTokenExpiry,
      issuer: 'wappler-auth',
      audience: 'wappler-app'
    }
  );
}

function generateTokens(user) {
  const jwt = require('jsonwebtoken');

  const accessToken = jwt.sign(
    {
      id: user.id,
      email: user.email,
      type: 'access'
    },
    config.auth.secret,
    {
      expiresIn: config.auth.tokens.accessTokenExpiry,
      issuer: 'wappler-auth',
      audience: 'wappler-app'
    }
  );

  const refreshToken = jwt.sign(
    {
      id: user.id,
      email: user.email,
      type: 'refresh'
    },
    config.auth.secret,
    {
      expiresIn: config.auth.tokens.refreshTokenExpiry,
      issuer: 'wappler-auth',
      audience: 'wappler-app'
    }
  );

  return {
    accessToken,
    refreshToken,
    expiresIn: config.auth.tokens.accessTokenExpiry
  };
}

function sanitizeUser(user) {
  // Remove sensitive fields before sending to client
  const { password_hash, email_verification_token, password_reset_token,
          two_factor_secret, login_attempts, locked_until, ...safeUser } = user;
  return safeUser;
}