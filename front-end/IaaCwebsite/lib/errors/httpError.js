class HttpError extends Error {
  name = 'HttpError';
  url = "";
  status = 0;
  statusText = "";
  body = "";

  constructor(options) {
    super(`Request "${options.url || ''}" responded with ${options.status || ''} ${options.statusText || ''}`);
    this.name = "HttpError";
    this.status = options.status;
    this.statusText = options.statusText;
    this.body = options.body;
  }
}

module.exports = HttpError;
