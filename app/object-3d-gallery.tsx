"use client";

import { useMemo, useState } from "react";
import object3DVersionData from "../data/object-3d-versions.json";
import {
  ModelTurntable,
  ObjectAssetInspector,
  primaryObject3DVersion,
  type Object3DRecord,
} from "./object-asset-inspector";
import { objectInventoryManifest as inventory } from "./object-inventory-data";

type Object3DManifest = {
  schemaVersion: number;
  updatedAt: string;
  objects: Object3DRecord[];
};

type Object3DGalleryProps = {
  initialObjectId?: string;
  onModeChange?: () => void;
};

const manifest = object3DVersionData as Object3DManifest;

function formatCount(value: number) {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(2)}m`;
  }
  return `${Math.round(value / 1_000)}k`;
}

export function Object3DGallery({
  initialObjectId = "",
  onModeChange,
}: Object3DGalleryProps) {
  const objectById = useMemo(
    () => new Map(inventory.objects.map((item) => [item.id, item])),
    [],
  );
  const records = useMemo(
    () =>
      manifest.objects.flatMap((record) => {
        const object = objectById.get(record.objectId);
        return object ? [{ object, record }] : [];
      }),
    [objectById],
  );
  const validInitialObjectId = records.some(
    ({ object }) => object.id === initialObjectId,
  )
    ? initialObjectId
    : records[0]?.object.id || "";
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");
  const [versionPanelOpen, setVersionPanelOpen] = useState(
    Boolean(initialObjectId),
  );
  const [versionObjectId, setVersionObjectId] = useState(
    validInitialObjectId,
  );

  const categories = useMemo(
    () => [
      "All",
      ...Array.from(
        new Set(records.map(({ object }) => object.category)),
      ).sort(),
    ],
    [records],
  );
  const filteredRecords = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return records.filter(({ object, record }) => {
      if (category !== "All" && object.category !== category) return false;
      if (!normalizedQuery) return true;
      return [
        object.name,
        object.category,
        ...record.versions.flatMap((version) => [
          version.label,
          version.provider,
          version.note,
        ]),
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [category, query, records]);

  const panelRecord =
    records.find(({ object }) => object.id === versionObjectId) || records[0];

  return (
    <div
      className={`three-d-workspace ${
        versionPanelOpen ? "right-inspector-open" : ""
      }`}
    >
      <section className="three-d-main">
        <nav className="object-sticky-nav" aria-label="3D object filters">
          <div className="object-filter-bar">
            <div className="object-category-tabs" role="list">
              <div className="object-mode-tabs">
                <button type="button" onClick={onModeChange}>
                  Objects
                </button>
                <button
                  type="button"
                  className="active"
                  aria-current="page"
                >
                  3D
                  <b className="feedback-nav-count">{records.length}</b>
                </button>
              </div>
              {categories.map((item) => {
                const count =
                  item === "All"
                    ? filteredRecords.length
                    : records.filter(({ object }) => object.category === item)
                        .length;
                return (
                  <button
                    key={item}
                    className={category === item ? "active" : ""}
                    onClick={() => setCategory(item)}
                    aria-pressed={category === item}
                  >
                    {item}
                    {category === item && (
                      <b className="feedback-nav-count">{count}</b>
                    )}
                  </button>
                );
              })}
            </div>
            <label className="object-search">
              <span>Search</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find a 3D object"
                aria-label="Search 3D objects"
              />
            </label>
          </div>
        </nav>

        <div className="three-d-results">
          {filteredRecords.length ? (
            <div className="three-d-grid">
              {filteredRecords.map(({ object, record }) => {
                const primaryVersion = primaryObject3DVersion(record);
                const pickerOpen =
                  versionPanelOpen && versionObjectId === object.id;
                return (
                  <article className="three-d-card" key={object.id}>
                    <button
                      type="button"
                      className={`three-d-frame object-thumbnail-button ${
                        pickerOpen ? "picker-open" : ""
                      }`}
                      aria-label={`Open ${object.name} details`}
                      aria-expanded={pickerOpen}
                      aria-controls="object-asset-panel"
                      onClick={() => {
                        setVersionObjectId(object.id);
                        setVersionPanelOpen(true);
                      }}
                    >
                      {primaryVersion ? (
                        <ModelTurntable
                          className="three-d-model-viewer"
                          src={primaryVersion.model}
                          poster={primaryVersion.thumbnail}
                          alt={`Slowly rotating 3D model of ${object.name}`}
                          motionSeed={records.findIndex(
                            ({ object: item }) => item.id === object.id,
                          )}
                        />
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={object.image} alt={object.name} />
                      )}
                      {record.versions.length > 1 && primaryVersion && (
                        <span className="three-d-kind">
                          {primaryVersion.label}
                        </span>
                      )}
                    </button>
                    <div className="object-card-copy">
                      <button
                        type="button"
                        className="object-name-button"
                        aria-expanded={pickerOpen}
                        aria-controls="object-asset-panel"
                        onClick={() => {
                          setVersionObjectId(object.id);
                          setVersionPanelOpen(true);
                        }}
                      >
                        {object.name}
                      </button>
                      <span>{object.category}</span>
                    </div>
                    <p className="three-d-card-meta">
                      {primaryVersion
                        ? `${primaryVersion.provider} · ${formatCount(
                            primaryVersion.faces,
                          )} faces`
                        : `${object.sourceFiles.length} references`}
                    </p>
                  </article>
                );
              })}
            </div>
          ) : (
            <p className="object-no-results">
              No 3D objects match this filter.
            </p>
          )}
        </div>
      </section>

      <ObjectAssetInspector
        open={versionPanelOpen}
        onOpenChange={setVersionPanelOpen}
        object={panelRecord?.object || null}
        record={panelRecord?.record || null}
      />
    </div>
  );
}
