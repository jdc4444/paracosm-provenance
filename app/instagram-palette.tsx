import deckPaletteData from "../data/animation-deck-palette.json";
import paletteData from "../data/instagram-palette.json";

type PaletteColor = {
  id: string;
  name: string;
  hex: string;
  family: string;
  share: number;
  hue: number;
  saturation: number;
  lightness: number;
};

type PaletteFamilyColor = {
  id: string;
  name: string;
  hex: string;
  share: number;
};

type PaletteFamily = {
  id: string;
  name: string;
  description: string;
  share: number;
  colors: PaletteFamilyColor[];
};

type DeckShade = {
  id: string;
  name: string;
  hex: string;
  family: string;
  hue: number;
  saturation: number;
  lightness: number;
  role: string;
};

const palette = paletteData as {
  account: string;
  auditRange: {
    from: string;
    to: string;
  };
  postsReviewed: number;
  postsWithSavedStills: number;
  sourceImageCount: number;
  methodology: string;
  mainColors: PaletteColor[];
  families: PaletteFamily[];
  hueFamilies: Array<{
    id: string;
    name: string;
    share: number;
    colors: string[];
  }>;
  featuredSourceFiles: string[];
};

const deckPalette = deckPaletteData as {
  sourceDeck: string;
  slideCount: number;
  sampledPixels: number;
  methodology: string;
  summary: string;
  addedShades: DeckShade[];
};

function swatchInk(hex: string) {
  const value = Number.parseInt(hex.slice(1), 16);
  const red = (value >> 16) & 255;
  const green = (value >> 8) & 255;
  const blue = value & 255;
  const luminance =
    (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
  return luminance > 0.58 ? "#111111" : "#ffffff";
}

export function InstagramPalette() {
  return (
    <section className="instagram-palette palette-is-storybook">
      <header className="palette-cover">
        <div className="palette-cover-copy">
          <p className="palette-kicker">
            @{palette.account} · Storybook palette · deck first
          </p>
          <h2>Storybook warmth leads. Every archive color still has a place.</h2>
          <p className="palette-intro">
            The eight ANIMATION shades form the lead system, while all sixteen
            measured Instagram anchors remain as support. The result keeps the
            full range, but gives the warmer, stranger, more nostalgic colors
            the first word.
          </p>
          <dl className="palette-audit">
            <div>
              <dt>Lead shades</dt>
              <dd>{deckPalette.addedShades.length} deck anchors</dd>
            </div>
            <div>
              <dt>Support colors</dt>
              <dd>{palette.mainColors.length} archive anchors</dd>
            </div>
            <div>
              <dt>Working system</dt>
              <dd>
                {deckPalette.addedShades.length + palette.mainColors.length}{" "}
                colors
              </dd>
            </div>
          </dl>
        </div>

        <div className="palette-cover-field" aria-label="Dominant color field">
          <div className="palette-base-field">
            {palette.mainColors.map((color) => (
              <span
                key={color.id}
                style={{
                  backgroundColor: color.hex,
                  flexGrow: Math.max(1, color.share),
                }}
                title={`${color.name} · ${color.hex} · ${color.share}%`}
              />
            ))}
          </div>
          <div
            className="palette-deck-field"
            aria-label={`${deckPalette.addedShades.length} lead shades from ANIMATION`}
          >
            {deckPalette.addedShades.map((color) => (
              <span
                key={color.id}
                style={{ backgroundColor: color.hex }}
                title={`${color.name} · ${color.hex}`}
              />
            ))}
          </div>
        </div>
      </header>

      <main className="palette-main">
        <section className="palette-section" aria-labelledby="palette-main-colors">
          <header className="palette-section-heading">
            <div>
              <p>02 / Archive support</p>
              <h3 id="palette-main-colors">Every measured color, retained</h3>
            </div>
            <small>
              {palette.mainColors.length} supporting anchors · original shares
              shown
            </small>
          </header>

          <div className="palette-main-grid">
            {palette.mainColors.map((color, index) => (
              <article className="palette-main-swatch" key={color.id}>
                <div
                  style={{
                    backgroundColor: color.hex,
                    color: swatchInk(color.hex),
                  }}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <b>{color.share.toFixed(1)}%</b>
                </div>
                <h4>{color.name}</h4>
                <p>
                  <code>{color.hex.toUpperCase()}</code>
                  <span>
                    H{color.hue} · S{color.saturation} · L{color.lightness}
                  </span>
                </p>
              </article>
            ))}
          </div>
        </section>

        <section
          className="palette-section palette-deck-extension"
          aria-labelledby="palette-deck-shades"
        >
            <header className="palette-section-heading">
              <div>
                <p>01 / Primary palette</p>
                <h3 id="palette-deck-shades">
                  The storybook colors take the lead
                </h3>
              </div>
              <small>
                {deckPalette.slideCount} slides ·{" "}
                {deckPalette.addedShades.length} primary anchors
              </small>
            </header>

            <div className="palette-deck-summary">
              <p>
                Storybook red, orange, marigold, cream, faded rose, midnight
                blue, plum, and teal establish the emotional tone; the complete
                Instagram index follows as a flexible supporting range.
              </p>
              <dl>
                <div>
                  <dt>Warm structure</dt>
                  <dd>Red · orange · marigold · cream</dd>
                </div>
                <div>
                  <dt>Soft bridge</dt>
                  <dd>Faded rose · velvet plum</dd>
                </div>
                <div>
                  <dt>Cool depth</dt>
                  <dd>Midnight blue · patina teal</dd>
                </div>
              </dl>
            </div>

            <div className="palette-deck-grid">
              {deckPalette.addedShades.map((color, index) => (
                <article className="palette-deck-swatch" key={color.id}>
                  <div
                    style={{
                      backgroundColor: color.hex,
                      color: swatchInk(color.hex),
                    }}
                  >
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <code>{color.hex.toUpperCase()}</code>
                  </div>
                  <h4>{color.name}</h4>
                  <p>{color.role}</p>
                  <small>
                    H{color.hue} · S{color.saturation} · L{color.lightness}
                  </small>
                </article>
              ))}
            </div>

            <p className="palette-method palette-deck-method">
              <span>Method</span>
              {deckPalette.methodology} This hierarchy does not change the
              evidence: deck shades lead, and every measured archive color
              remains visible with its original share.
            </p>
        </section>

        <section className="palette-formula" aria-label="Palette formula">
          <article>
            <span>Lead</span>
            <strong>{deckPalette.addedShades.length}</strong>
            <h3>Storybook anchors</h3>
            <p>The deck-derived colors set tone, warmth, and atmosphere.</p>
          </article>
          <article>
            <span>Support</span>
            <strong>{palette.mainColors.length}</strong>
            <h3>Archive anchors</h3>
            <p>
              Every measured black, copper, blue, red, and neutral remains
              available.
            </p>
          </article>
          <article>
            <span>System</span>
            <strong>
              {deckPalette.addedShades.length + palette.mainColors.length}
            </strong>
            <h3>One expanded range</h3>
            <p>New colors lead; established colors add precision and range.</p>
          </article>
        </section>

        <section className="palette-section" aria-labelledby="palette-hues">
          <header className="palette-section-heading">
            <div>
              <p>03 / Hues</p>
              <h3 id="palette-hues">Chromatic rhythm</h3>
            </div>
            <small>
              Archive support field · neutral pixels removed · original shares
            </small>
          </header>

          <div className="palette-hue-list">
            {palette.hueFamilies.map((family) => (
              <article key={family.id}>
                <header>
                  <h4>{family.name}</h4>
                  <b>{family.share.toFixed(1)}%</b>
                </header>
                <div className="palette-hue-track">
                  <span
                    style={{
                      width: `${family.share}%`,
                      background: `linear-gradient(90deg, ${family.colors.join(
                        ", ",
                      )})`,
                    }}
                  />
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="palette-section" aria-labelledby="palette-families">
          <header className="palette-section-heading">
            <div>
              <p>04 / Families</p>
              <h3 id="palette-families">Working color families</h3>
            </div>
            <small>All archive families remain active support colors</small>
          </header>

          <div className="palette-family-grid">
            {palette.families.map((family, index) => (
              <article className="palette-family-card" key={family.id}>
                <header>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <b>{family.share.toFixed(1)}%</b>
                </header>
                <div className="palette-family-strip">
                  {family.colors.map((color) => (
                    <span
                      key={color.id}
                      style={{
                        width: `${color.share}%`,
                        backgroundColor: color.hex,
                      }}
                      title={`${color.name} · ${color.hex}`}
                    />
                  ))}
                </div>
                <h4>{family.name}</h4>
                <p>{family.description}</p>
                <ul>
                  {family.colors.map((color) => (
                    <li key={color.id}>
                      <i style={{ backgroundColor: color.hex }} />
                      <span>{color.name}</span>
                      <code>{color.hex.toUpperCase()}</code>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section className="palette-section palette-source-section">
          <header className="palette-section-heading">
            <div>
              <p>05 / Source field</p>
              <h3>Where the colors live</h3>
            </div>
            <small>
              {palette.postsWithSavedStills} posts with archived stills
            </small>
          </header>
          <div className="palette-source-grid">
            {palette.featuredSourceFiles.map((sourceFile) => (
              <figure key={sourceFile}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`/archive/objects/sources/wardrobe/${sourceFile}`}
                  alt=""
                />
              </figure>
            ))}
          </div>
          <p className="palette-method">
            <span>Method</span>
            {palette.methodology}
          </p>
        </section>
      </main>
    </section>
  );
}
