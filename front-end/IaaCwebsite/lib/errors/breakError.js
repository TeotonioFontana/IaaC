class BreakError extends Error {
  name = 'BreakError';

  constructor(options) {
    super('Break');
  }
}

module.exports = BreakError;
