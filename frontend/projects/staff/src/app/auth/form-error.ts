import { HttpErrorResponse } from '@angular/common/http';

export function extractErrorMessage(err: unknown): string {
  if (!(err instanceof HttpErrorResponse)) {
    return 'Something went wrong. Please try again.';
  }
  if (err.status === 0) {
    return 'Network error. Please check your connection.';
  }
  const body = err.error;
  if (body && typeof body === 'object') {
    if (typeof body.detail === 'string') {
      return body.detail;
    }
    const firstKey = Object.keys(body)[0];
    if (firstKey) {
      const val = body[firstKey];
      if (Array.isArray(val) && typeof val[0] === 'string') {
        return `${firstKey}: ${val[0]}`;
      }
      if (typeof val === 'string') {
        return `${firstKey}: ${val}`;
      }
    }
  }
  if (typeof body === 'string' && body) {
    return body;
  }
  return `Error ${err.status}`;
}
