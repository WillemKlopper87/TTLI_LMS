"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

interface PublicLessonRow {
  id: string;
  title: string;
  position: number;
  activity_type: string;
  access_level: string;
}

interface PublicModuleRow {
  id: string;
  title: string;
  position: number;
  lessons: PublicLessonRow[];
}

interface PublicCurriculumResponse {
  course_id: string;
  title: string;
  description: string | null;
  modules: PublicModuleRow[];
}

/**
 * A published course's public curriculum — no auth required
 * (GET /api/v1/public/courses/{id}/curriculum). Free-preview lessons
 * (access_level="public") link straight to /preview/{lessonId}; every
 * other lesson is shown but not linked, same as any other product page
 * showing what's inside before purchase.
 */
export default function CourseDetailPage() {
  const params = useParams<{ courseId: string }>();
  const [curriculum, setCurriculum] = useState<PublicCurriculumResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`/api/bff/public/courses/${params.courseId}/curriculum`)
      .then(async (resp) => {
        if (!resp.ok) {
          setError(true);
          return;
        }
        setCurriculum(await resp.json());
      })
      .catch(() => setError(true));
  }, [params.courseId]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      {error ? (
        <p style={{ fontSize: "0.875rem", color: "var(--muted)" }}>
          This course could not be found.{" "}
          <Link href="/catalogue" style={{ color: "var(--brand-ink)" }}>
            Back to the catalogue
          </Link>
          .
        </p>
      ) : curriculum === null ? (
        <p style={{ fontSize: "0.875rem", color: "var(--faint)" }}>Loading…</p>
      ) : (
        <>
          <p className="eyebrow">Curriculum</p>
          <h1 className="serif mt-2" style={{ fontSize: "1.75rem" }}>
            {curriculum.title}
          </h1>
          {curriculum.description ? (
            <p className="mt-2" style={{ fontSize: "0.9375rem", color: "var(--muted)" }}>
              {curriculum.description}
            </p>
          ) : null}

          <div className="mt-8 flex flex-col gap-6">
            {curriculum.modules.map((module) => (
              <div key={module.id}>
                <b style={{ fontSize: "0.9375rem" }}>{module.title}</b>
                <div className="mt-2 flex flex-col gap-1">
                  {module.lessons.map((lesson) => (
                    <div
                      key={lesson.id}
                      className="card flex items-center justify-between gap-2 p-3"
                    >
                      <span style={{ fontSize: "0.875rem" }}>{lesson.title}</span>
                      {lesson.access_level === "public" ? (
                        <Link href={`/preview/${lesson.id}`} className="tag tag--brand">
                          Preview
                        </Link>
                      ) : (
                        <span className="tag tag--mute">{lesson.activity_type}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-8">
            <Link href="/catalogue" className="btn btn--primary">
              See enrolment options
            </Link>
          </div>
        </>
      )}
    </main>
  );
}
