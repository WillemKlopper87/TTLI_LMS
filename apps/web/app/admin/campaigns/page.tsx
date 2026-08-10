"use client";

import { useEffect, useState } from "react";

import { getAccessToken } from "@/lib/session";

interface Segment {
  id: string;
  name: string;
  criteria: Record<string, unknown>;
}

interface Template {
  id: string;
  name: string;
  subject: string;
  body_text: string;
}

interface Campaign {
  id: string;
  name: string;
  template_id: string;
  segment_id: string;
  status: string;
  sent_at: string | null;
}

interface CampaignStats {
  campaign: Campaign;
  sent: number;
  suppressed: number;
  bounced: number;
}

const STATUS_TAG: Record<string, string> = {
  draft: "tag--mute",
  sending: "tag--live",
  sent: "tag--done",
};

/**
 * Segments, templates, campaigns (02 §10, REQ-CRM-04) — a segment's
 * criteria matches only lead stage/UTM fields, never a stored address
 * list; sending honours marketing consent and the suppression list
 * automatically, reported back in the send result.
 */
export default function CampaignsScreen() {
  const [segments, setSegments] = useState<Segment[] | null>(null);
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [segmentName, setSegmentName] = useState("");
  const [segmentStage, setSegmentStage] = useState("");

  const [templateName, setTemplateName] = useState("");
  const [templateSubject, setTemplateSubject] = useState("");
  const [templateBody, setTemplateBody] = useState("");

  const [campaignName, setCampaignName] = useState("");
  const [campaignTemplateId, setCampaignTemplateId] = useState("");
  const [campaignSegmentId, setCampaignSegmentId] = useState("");

  const [sendBusy, setSendBusy] = useState<string | null>(null);
  const [statsId, setStatsId] = useState<string | null>(null);
  const [stats, setStats] = useState<CampaignStats | null>(null);

  async function authedFetch(path: string, init: RequestInit = {}) {
    const token = getAccessToken();
    return fetch(path, { ...init, headers: { ...init.headers, Authorization: `Bearer ${token}` } });
  }

  async function loadAll() {
    const [s, t, c] = await Promise.all([
      authedFetch("/api/bff/segments"),
      authedFetch("/api/bff/email-templates"),
      authedFetch("/api/bff/campaigns"),
    ]);
    if (s.status === 403 || t.status === 403 || c.status === 403) {
      setError("forbidden");
      return;
    }
    setSegments((await s.json()).items);
    setTemplates((await t.json()).items);
    setCampaigns((await c.json()).items);
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createSegment() {
    if (!segmentName.trim()) return;
    const criteria: Record<string, string> = {};
    if (segmentStage.trim()) criteria.stage = segmentStage.trim();
    const resp = await authedFetch("/api/bff/segments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: segmentName.trim(), criteria }),
    });
    if (resp.ok) {
      setSegmentName("");
      setSegmentStage("");
      await loadAll();
    }
  }

  async function createTemplate() {
    if (!templateName.trim() || !templateSubject.trim() || !templateBody.trim()) return;
    const resp = await authedFetch("/api/bff/email-templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: templateName.trim(),
        subject: templateSubject.trim(),
        body_text: templateBody.trim(),
      }),
    });
    if (resp.ok) {
      setTemplateName("");
      setTemplateSubject("");
      setTemplateBody("");
      await loadAll();
    }
  }

  async function createCampaign() {
    if (!campaignName.trim() || !campaignTemplateId || !campaignSegmentId) return;
    const resp = await authedFetch("/api/bff/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: campaignName.trim(),
        template_id: campaignTemplateId,
        segment_id: campaignSegmentId,
      }),
    });
    if (resp.ok) {
      setCampaignName("");
      await loadAll();
    }
  }

  async function sendCampaign(id: string) {
    setSendBusy(id);
    setError(null);
    const resp = await authedFetch(`/api/bff/campaigns/${id}/send`, { method: "POST" });
    setSendBusy(null);
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      setError(body?.error?.message ?? "Could not send that campaign.");
      return;
    }
    await loadAll();
    await viewStats(id);
  }

  async function viewStats(id: string) {
    setStatsId(id);
    const resp = await authedFetch(`/api/bff/campaigns/${id}`);
    if (resp.ok) setStats(await resp.json());
  }

  if (error === "forbidden") {
    return (
      <p style={{ fontSize: "0.8125rem", color: "var(--muted)" }}>
        Your account does not have permission to manage campaigns.
      </p>
    );
  }
  if (segments === null || templates === null || campaigns === null) {
    return <p style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>Loading…</p>;
  }

  return (
    <>
      <h1 className="serif" style={{ fontSize: "1.5rem" }}>
        Campaigns
      </h1>

      {error ? (
        <p role="alert" className="mt-2" style={{ fontSize: "0.8125rem", color: "var(--stop)" }}>
          {error}
        </p>
      ) : null}

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <b style={{ fontSize: "0.875rem" }}>New segment</b>
          <p className="mt-1" style={{ fontSize: "0.75rem", color: "var(--muted)" }}>
            Matches leads by pipeline stage — leave blank to target everyone.
          </p>
          <label className="field mt-3">
            <b>Name</b>
            <input
              className="input"
              value={segmentName}
              onChange={(e) => setSegmentName(e.target.value)}
              placeholder="Qualified leads"
            />
          </label>
          <label className="field mt-3">
            <b>Stage (optional)</b>
            <select
              className="input"
              value={segmentStage}
              onChange={(e) => setSegmentStage(e.target.value)}
            >
              <option value="">Any</option>
              <option value="new">new</option>
              <option value="contacted">contacted</option>
              <option value="qualified">qualified</option>
            </select>
          </label>
          <button
            type="button"
            className="btn btn--primary mt-3"
            disabled={!segmentName.trim()}
            onClick={createSegment}
          >
            Create segment
          </button>

          <div className="mt-4 flex flex-col gap-1">
            {segments.map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-2">
                <span style={{ fontSize: "0.8125rem" }}>{s.name}</span>
                <span className="mono" style={{ fontSize: "0.6875rem", color: "var(--muted)" }}>
                  {Object.keys(s.criteria).length === 0 ? "everyone" : JSON.stringify(s.criteria)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="card p-5">
          <b style={{ fontSize: "0.875rem" }}>New template</b>
          <label className="field mt-3">
            <b>Name</b>
            <input
              className="input"
              value={templateName}
              onChange={(e) => setTemplateName(e.target.value)}
              placeholder="Q3 nudge"
            />
          </label>
          <label className="field mt-3">
            <b>Subject</b>
            <input
              className="input"
              value={templateSubject}
              onChange={(e) => setTemplateSubject(e.target.value)}
              placeholder="A programme for {{first_name}}"
            />
          </label>
          <label className="field mt-3">
            <b>Body (plain text)</b>
            <textarea
              className="input"
              style={{ minHeight: "5rem" }}
              value={templateBody}
              onChange={(e) => setTemplateBody(e.target.value)}
              placeholder="Hi {{first_name}}, thanks for your interest."
            />
          </label>
          <button
            type="button"
            className="btn btn--primary mt-3"
            disabled={!templateName.trim() || !templateSubject.trim() || !templateBody.trim()}
            onClick={createTemplate}
          >
            Create template
          </button>

          <div className="mt-4 flex flex-col gap-1">
            {templates.map((t) => (
              <span key={t.id} style={{ fontSize: "0.8125rem" }}>
                {t.name} — <span style={{ color: "var(--muted)" }}>{t.subject}</span>
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-6">
        <div className="card p-5">
          <b style={{ fontSize: "0.875rem" }}>New campaign</b>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="field">
              <b>Name</b>
              <input
                className="input"
                value={campaignName}
                onChange={(e) => setCampaignName(e.target.value)}
                placeholder="Q3 push"
              />
            </label>
            <label className="field">
              <b>Template</b>
              <select
                className="input"
                value={campaignTemplateId}
                onChange={(e) => setCampaignTemplateId(e.target.value)}
              >
                <option value="">Choose…</option>
                {templates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <b>Segment</b>
              <select
                className="input"
                value={campaignSegmentId}
                onChange={(e) => setCampaignSegmentId(e.target.value)}
              >
                <option value="">Choose…</option>
                {segments.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn--primary"
              disabled={!campaignName.trim() || !campaignTemplateId || !campaignSegmentId}
              onClick={createCampaign}
            >
              Create draft
            </button>
          </div>
        </div>

        {campaigns.length === 0 ? (
          <p className="mt-4" style={{ fontSize: "0.8125rem", color: "var(--faint)" }}>
            No campaigns yet.
          </p>
        ) : (
          <div className="table-wrap mt-4">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Status</th>
                  <th scope="col"></th>
                  <th scope="col"></th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => (
                  <tr key={c.id}>
                    <td>{c.name}</td>
                    <td>
                      <span className={`tag ${STATUS_TAG[c.status] ?? "tag--mute"}`}>
                        {c.status}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--primary"
                        disabled={c.status !== "draft" || sendBusy === c.id}
                        onClick={() => sendCampaign(c.id)}
                      >
                        Send
                      </button>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => viewStats(c.id)}
                      >
                        {statsId === c.id ? "Refresh" : "Stats"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {statsId && stats ? (
          <div className="card mt-3 p-4 flex flex-wrap gap-4" style={{ fontSize: "0.8125rem" }}>
            <span>
              Sent <b className="mono">{stats.sent}</b>
            </span>
            <span>
              Suppressed <b className="mono">{stats.suppressed}</b>
            </span>
            <span>
              Bounced <b className="mono">{stats.bounced}</b>
            </span>
          </div>
        ) : null}
      </section>
    </>
  );
}
