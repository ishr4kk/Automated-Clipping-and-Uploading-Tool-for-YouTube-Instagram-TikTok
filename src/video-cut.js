

const CUT_MODES = ["starting", "anywhere", "end"];


function validateCutConfig({ cut = "", lengthSeconds = 0 } = {}) {
  const rawCut = String(cut || "").trim().toLowerCase();
  const rawLength = String(lengthSeconds === undefined ? "" : lengthSeconds).trim();

  const cutSet = rawCut !== "";



  const lengthSet = rawLength !== "" && Number(rawLength) !== 0;

  if (!cutSet && !lengthSet) {
    return { mode: null, lengthSeconds: 0 };
  }
  if (cutSet && !lengthSet) {
    throw new Error(
      `VIDEO_CUT is set to "${rawCut}" but VIDEO_LENGTH_SECONDS is missing or not ` +
        `greater than zero. Set it to a positive number of seconds (e.g. 30).`
    );
  }
  if (!cutSet && lengthSet) {
    throw new Error(
      `VIDEO_LENGTH_SECONDS is set to "${rawLength}" but VIDEO_CUT is missing. ` +
        `Set both values in .env (VIDEO_CUT=starting|anywhere|end).`
    );
  }

  if (!CUT_MODES.includes(rawCut)) {
    throw new Error(
      `Invalid VIDEO_CUT value "${rawCut}". Allowed values: ${CUT_MODES.join(", ")}.`
    );
  }

  const length = Number(rawLength);
  if (!Number.isFinite(length) || length <= 0) {
    throw new Error(
      `Invalid VIDEO_LENGTH_SECONDS value "${rawLength}". It must be a positive number of seconds.`
    );
  }

  return { mode: rawCut, lengthSeconds: length };
}


function computeCutPlan(sourceDurationSeconds, { cut, lengthSeconds, rng = Math.random } = {}) {
  const duration = Number(sourceDurationSeconds);
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`Invalid source duration: ${sourceDurationSeconds}`);
  }

  const { mode, lengthSeconds: length } = validateCutConfig({ cut, lengthSeconds });

  if (mode === null) {
    return {
      mode: "legacy",
      startSeconds: 0,
      limitSeconds: null,
      reason: "VIDEO_CUT/VIDEO_LENGTH_SECONDS not set; using legacy duration rules",
    };
  }



  if (length >= duration) {
    return {
      mode: "full",
      startSeconds: 0,
      limitSeconds: null,
      reason:
        `source ${duration.toFixed(1)}s is not longer than the required ${length}s; ` +
        `using the entire source (final length = min(${duration.toFixed(1)}s, ${length}s))`,
    };
  }

  if (mode === "starting") {
    return {
      mode,
      startSeconds: 0,
      limitSeconds: length,
      reason: `cut mode "starting": first ${length}s of the source`,
    };
  }

  if (mode === "end") {
    const startSeconds = duration - length;
    return {
      mode,
      startSeconds,
      limitSeconds: length,
      reason: `cut mode "end": last ${length}s of the source (starts at ${startSeconds.toFixed(1)}s)`,
    };
  }



  const maxStart = duration - length;
  const startSeconds = maxStart <= 0 ? 0 : rng() * maxStart;
  return {
    mode,
    startSeconds,
    limitSeconds: length,
    reason: `cut mode "anywhere": random ${length}s clip (starts at ${startSeconds.toFixed(1)}s)`,
  };
}

module.exports = {
  CUT_MODES,
  validateCutConfig,
  computeCutPlan,
};
