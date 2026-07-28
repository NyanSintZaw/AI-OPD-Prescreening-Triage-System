/**
 * The two decisions in this app that are easy to get subtly wrong, kept free
 * of Electron imports so `npm test` can exercise them under plain Node.
 */

/**
 * Toast only when the queue grows. `prev < 0` means "no successful poll yet",
 * so launching with a full queue stays quiet — otherwise every login would
 * fire a notification for cases the nurse already knows about.
 */
function shouldNotify(prev, next) {
  return prev >= 0 && next > prev;
}

/**
 * Backend admin tokens live in memory and die with the API process, so a 401
 * is routine, not exceptional. Log in and retry exactly once; a second 401
 * means the stored credentials are wrong and retrying would just lock us in a
 * loop against the login endpoint.
 */
async function withAuthRetry(call, login) {
  let res = await call();
  if (res.status !== 401) return res;
  if (!(await login())) return res;
  return call();
}

module.exports = { shouldNotify, withAuthRetry };
