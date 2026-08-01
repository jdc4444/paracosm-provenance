"use client";

import { useMemo, useState } from "react";
import object3DVersionData from "../data/object-3d-versions.json";
import {
  ModelTurntable,
  ObjectAssetInspector,
  primaryObject3DVersion,
  type Object3DRecord,
} from "./object-asset-inspector";
import {
  productionNotesForObject,
  productionNoteSummary,
} from "./object-production-metadata";
import { objectInventoryManifest as manifest } from "./object-inventory-data";
import {
  reconstructionModeLabel,
  reconstructionStrategyForObject,
} from "./object-reconstruction-metadata";

const object3DRecords = (
  object3DVersionData as { objects: Object3DRecord[] }
).objects;
const object3DById = new Map(
  object3DRecords.map((record) => [record.objectId, record]),
);

const architectureObjectOrder = new Map(
  [
    "house-b",
    "roof",
    "chimney",
    "window",
    "front-canopy",
    "outdoor-plants",
    "tower",
    "bridge",
    "glass-window-display",
    "lantern",
    "stair-railing",
    "door",
    "wall-panel",
  ].map((id, index) => [id, index]),
);

export function ObjectInventory({
  onModeChange,
}: {
  onModeChange?: () => void;
}) {
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelObjectId, setPanelObjectId] = useState(
    manifest.objects[0]?.id || "",
  );
  const categories = useMemo(
    () => [
      "All",
      ...Array.from(
        new Set(manifest.objects.map((item) => item.category)),
      ).sort(),
    ],
    [],
  );
  const objects = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filteredObjects = manifest.objects.filter((item) => {
      if (category !== "All" && item.category !== category) return false;
      if (!normalizedQuery) return true;
      return `${item.name} ${item.category}`.toLowerCase().includes(normalizedQuery);
    });
    if (category !== "Architecture") return filteredObjects;
    return [...filteredObjects].sort((a, b) => {
      const aOrder = architectureObjectOrder.get(a.id) ?? Number.MAX_SAFE_INTEGER;
      const bOrder = architectureObjectOrder.get(b.id) ?? Number.MAX_SAFE_INTEGER;
      return aOrder - bOrder;
    });
  }, [category, query]);
  const panelObject =
    manifest.objects.find((item) => item.id === panelObjectId) || null;
  const panelRecord = panelObject
    ? object3DById.get(panelObject.id) || null
    : null;

  return (
    <div
      className={`object-workspace-shell ${
        panelOpen ? "right-inspector-open" : ""
      }`}
    >
      <section className="object-workspace">
        <nav className="object-sticky-nav" aria-label="Object inventory filters">
          <div className="object-filter-bar">
            <div className="object-category-tabs" role="list">
              <div className="object-mode-tabs">
                <button
                  type="button"
                  className="active"
                  aria-current="page"
                >
                  Objects
                </button>
                <button type="button" onClick={onModeChange}>
                  3D
                  <b className="feedback-nav-count">
                    {object3DRecords.length}
                  </b>
                </button>
              </div>
              {categories.map((item) => (
                <button
                  key={item}
                  className={category === item ? "active" : ""}
                  onClick={() => setCategory(item)}
                  aria-pressed={category === item}
                >
                  {item}
                  {category === item && (
                    <b className="feedback-nav-count">{objects.length}</b>
                  )}
                </button>
              ))}
            </div>
            <label className="object-search">
              <span>Search</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find an object"
                aria-label="Search objects"
              />
            </label>
          </div>
        </nav>

        <div className="object-results">
          {objects.length ? (
            <div className="object-grid">
              {objects.map((item, index) => {
                const record = object3DById.get(item.id) || null;
                const primaryVersion = primaryObject3DVersion(record);
                const productionNotes = productionNotesForObject(item.id);
                const noteSummary = productionNoteSummary(productionNotes);
                const reconstructionStrategy =
                  reconstructionStrategyForObject(item);
                const selected = panelOpen && panelObjectId === item.id;
                return (
                  <article className="object-card" key={item.id}>
                    <button
                      type="button"
                      className={`object-frame object-thumbnail-button ${
                        primaryVersion ? "has-live-3d" : ""
                      } ${selected ? "picker-open" : ""}`}
                      aria-label={`Open ${item.name} details`}
                      aria-expanded={selected}
                      aria-controls="object-asset-panel"
                      onClick={() => {
                        setPanelObjectId(item.id);
                        setPanelOpen(true);
                      }}
                    >
                      {primaryVersion ? (
                        <ModelTurntable
                          className="object-card-model-viewer"
                          src={primaryVersion.model}
                          poster={primaryVersion.thumbnail}
                          alt={`Slowly rotating 3D model of ${item.name}`}
                          motionSeed={index}
                        />
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={item.image} alt={item.name} />
                      )}
                      {record && record.versions.length > 1 && (
                        <span className="three-d-kind">
                          {primaryVersion?.label}
                        </span>
                      )}
                    </button>
                    <div className="object-card-copy">
                      <button
                        type="button"
                        className="object-name-button"
                        aria-expanded={selected}
                        aria-controls="object-asset-panel"
                        onClick={() => {
                          setPanelObjectId(item.id);
                          setPanelOpen(true);
                        }}
                      >
                        {item.name}
                      </button>
                      <span>{item.category}</span>
                    </div>
                    <p>
                      {primaryVersion
                        ? `${primaryVersion.provider} · 3D`
                        : `${item.sourceFiles.length} ${
                            item.sourceFiles.length === 1
                              ? "reference"
                              : "references"
                          }`}
                      {reconstructionStrategy
                        ? ` · ${reconstructionModeLabel(
                            reconstructionStrategy.mode,
                          )}`
                        : ""}
                      {noteSummary ? ` · ${noteSummary}` : ""}
                    </p>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="object-no-results">No objects match this filter.</p>
          )}
        </div>
      </section>

      <ObjectAssetInspector
        open={panelOpen}
        onOpenChange={setPanelOpen}
        object={panelObject}
        record={panelRecord}
      />
    </div>
  );
}
