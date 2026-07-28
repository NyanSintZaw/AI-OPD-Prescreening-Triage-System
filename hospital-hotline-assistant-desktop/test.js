const assert = require('node:assert/strict');
const { shouldNotify, withAuthRetry } = require('./logic');

// --- shouldNotify -----------------------------------------------------------
assert.equal(shouldNotify(-1, 9), false, 'first poll must stay silent');
assert.equal(shouldNotify(0, 1), true, 'queue grew');
assert.equal(shouldNotify(3, 3), false, 'unchanged queue');
assert.equal(shouldNotify(3, 1), false, 'queue shrank (nurse approved cases)');

// --- withAuthRetry ----------------------------------------------------------
const run = async () => {
  let calls = 0;
  let logins = 0;

  // Happy path: no login, no retry.
  calls = 0;
  let res = await withAuthRetry(
    async () => (calls++, { status: 200 }),
    async () => (logins++, true),
  );
  assert.equal(res.status, 200);
  assert.equal(calls, 1);
  assert.equal(logins, 0);

  // Expired token: log in, retry once, succeed.
  calls = 0;
  logins = 0;
  res = await withAuthRetry(
    async () => (++calls === 1 ? { status: 401 } : { status: 200 }),
    async () => (logins++, true),
  );
  assert.equal(res.status, 200);
  assert.equal(calls, 2, 'exactly one retry');
  assert.equal(logins, 1);

  // Bad credentials: login fails, no retry — must not hammer /admin/login.
  calls = 0;
  logins = 0;
  res = await withAuthRetry(
    async () => (calls++, { status: 401 }),
    async () => (logins++, false),
  );
  assert.equal(res.status, 401);
  assert.equal(calls, 1, 'no retry when login failed');

  // Wrong password stored: login succeeds but the retry still 401s — stop there.
  calls = 0;
  logins = 0;
  res = await withAuthRetry(
    async () => (calls++, { status: 401 }),
    async () => (logins++, true),
  );
  assert.equal(res.status, 401);
  assert.equal(calls, 2, 'retry once and give up');
  assert.equal(logins, 1, 'no second login attempt');

  console.log('ok');
};

run();
