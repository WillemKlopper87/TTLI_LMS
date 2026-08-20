"use client";

/**
 * `/admin/courses/new` — step 1 only, with no course id yet. The first save
 * is `POST /courses`, after which the route becomes
 * `/admin/courses/{id}/edit?step=2` and never comes back here: the course
 * id in the URL is the whole of the wizard's resumability.
 */

import { useState } from "react";

import { useAdmin } from "../../admin-context";
import { StepBasics } from "../steps/step-basics";
import type { SkipKey, WizardContext } from "../types";
import { deriveStepStates } from "../wizard-api";

export default function NewCoursePage() {
  const { me } = useAdmin();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const noSkips: Record<SkipKey, boolean> = { rules: false, certification: false };

  const ctx: WizardContext = {
    courseId: null,
    course: null,
    outline: null,
    readiness: null,
    canEdit: me.permissions.includes("course:edit"),
    canPublish: me.permissions.includes("course:publish"),
    canManageProducts: me.permissions.includes("product:manage"),
    skips: noSkips,
    setSkip: () => undefined,
    reloadCourse: async () => undefined,
    reloadOutline: async () => undefined,
    reloadReadiness: async () => undefined,
    // eslint-disable-next-line react-hooks/purity -- runs on the save click, not during render
    markSaved: () => setSavedAt(Date.now()),
    setError,
    setNotice,
  };

  return (
    <div className="dash">
      <div className="dash-top">
        <div>
          <p className="eyebrow">Course setup</p>
          <h1>New course</h1>
        </div>
        <a className="btn btn--ghost" href="/admin/courses">
          All courses
        </a>
      </div>

      <StepBasics
        ctx={ctx}
        stepStates={deriveStepStates(null, null, null, noSkips)}
        onStep={() =>
          setNotice("Create the course first — every later step needs a course to write to.")
        }
        savedAt={savedAt}
        error={error}
        notice={notice}
      />
    </div>
  );
}
