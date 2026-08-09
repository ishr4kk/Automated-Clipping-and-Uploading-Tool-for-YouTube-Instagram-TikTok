
class SessionError extends Error {
  constructor(message) {
    super(message);
    this.name = "SessionError";
    this.code = "SESSION_ERROR";
  }
}

class UploadError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = "UploadError";
    this.code = "UPLOAD_ERROR";
    this.cause = options.cause;
  }
}

module.exports = { SessionError, UploadError };
