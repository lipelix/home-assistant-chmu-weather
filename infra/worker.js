// Asks GitHub to run the forecast publishing workflow.
//
// GitHub's own cron is unreliable for this: scheduled runs are delayed under
// load and dropped outright when the load is high enough, measured here at
// roughly one firing delivered every four hours whatever the schedule asked
// for. Cloudflare's cron triggers fire on time, so the clock lives here and
// the workflow keeps only workflow_dispatch.
//
// The workflow decides whether there is anything to publish: a run that finds
// the newest ALADIN run already published exits before downloading it, so
// polling often is cheap. There is no fetch handler on purpose - nothing
// should be able to trigger this from the internet.

async function dispatch(env) {
  const missing = [
    "GITHUB_TOKEN",
    "GITHUB_REPOSITORY",
    "GITHUB_WORKFLOW_FILE",
    "GITHUB_REF",
  ].filter((name) => !env[name]);
  if (missing.length > 0) {
    throw new Error(`missing required binding(s): ${missing.join(", ")}`);
  }

  const url =
    `https://api.github.com/repos/${env.GITHUB_REPOSITORY}` +
    `/actions/workflows/${env.GITHUB_WORKFLOW_FILE}/dispatches`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      // GitHub rejects API requests without one.
      "user-agent": "chmu-forecast-scheduler",
      "content-type": "application/json",
    },
    body: JSON.stringify({ ref: env.GITHUB_REF }),
  });

  // 204 is the documented success; anything else is worth failing on so that
  // it shows up in the Worker's logs rather than silently stopping the clock.
  if (response.status !== 204) {
    const body = await response.text();
    throw new Error(`dispatch failed: HTTP ${response.status} ${body}`);
  }
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(dispatch(env));
  },
};

export { dispatch };
