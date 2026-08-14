/* @ds-bundle: {"format":4,"namespace":"CRTArcadeDesignSystem_70e231","components":[{"name":"RARITY","sourcePath":"components/cards/RarityBadge.jsx"},{"name":"RarityBadge","sourcePath":"components/cards/RarityBadge.jsx"},{"name":"Scanlines","sourcePath":"components/cards/Scanlines.jsx"},{"name":"StatFigure","sourcePath":"components/cards/StatFigure.jsx"},{"name":"TradingCard","sourcePath":"components/cards/TradingCard.jsx"},{"name":"Badge","sourcePath":"components/core/Badge.jsx"},{"name":"Button","sourcePath":"components/core/Button.jsx"},{"name":"IconButton","sourcePath":"components/core/IconButton.jsx"},{"name":"Panel","sourcePath":"components/core/Panel.jsx"},{"name":"Tag","sourcePath":"components/core/Tag.jsx"},{"name":"Dialog","sourcePath":"components/feedback/Dialog.jsx"},{"name":"Toast","sourcePath":"components/feedback/Toast.jsx"},{"name":"Tooltip","sourcePath":"components/feedback/Tooltip.jsx"},{"name":"Checkbox","sourcePath":"components/forms/Checkbox.jsx"},{"name":"Field","sourcePath":"components/forms/Field.jsx"},{"name":"Input","sourcePath":"components/forms/Input.jsx"},{"name":"Radio","sourcePath":"components/forms/Radio.jsx"},{"name":"Select","sourcePath":"components/forms/Select.jsx"},{"name":"Switch","sourcePath":"components/forms/Switch.jsx"},{"name":"Tabs","sourcePath":"components/navigation/Tabs.jsx"}],"sourceHashes":{"components/cards/RarityBadge.jsx":"7363ac7d06bb","components/cards/Scanlines.jsx":"41ae70e9f05c","components/cards/StatFigure.jsx":"f6d1014e613c","components/cards/TradingCard.jsx":"9d6d1b8b8fd8","components/core/Badge.jsx":"0e7e99fc3226","components/core/Button.jsx":"b2615e25bcac","components/core/IconButton.jsx":"247d7732fd1b","components/core/Panel.jsx":"6ff441dfd73f","components/core/Tag.jsx":"921304d0be4e","components/feedback/Dialog.jsx":"739f800fc429","components/feedback/Toast.jsx":"f37a9561c8cf","components/feedback/Tooltip.jsx":"c22580f43e02","components/forms/Checkbox.jsx":"fdb5b7340545","components/forms/Field.jsx":"2830136b2591","components/forms/Input.jsx":"2ada4c37ee67","components/forms/Radio.jsx":"9ac0ec36fd11","components/forms/Select.jsx":"795e1d64b43a","components/forms/Switch.jsx":"92df1b795b5d","components/navigation/Tabs.jsx":"568e86f7242b","ui_kits/cabinet/AppShell.jsx":"e91927e8ab46","ui_kits/cabinet/BrowseScreen.jsx":"b086e16845ab","ui_kits/cabinet/CardDetailScreen.jsx":"4294787894e0","ui_kits/cabinet/DeckBuilderScreen.jsx":"82f87d02ea29","ui_kits/cabinet/PricesScreen.jsx":"5cc47a05f398","ui_kits/cabinet/data.js":"8ffffebc54a6"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.CRTArcadeDesignSystem_70e231 = window.CRTArcadeDesignSystem_70e231 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/cards/RarityBadge.jsx
try { (() => {
const RARITY = {
  common: {
    ink: 'var(--rarity-common)',
    bloom: 0,
    label: 'Common'
  },
  uncommon: {
    ink: 'var(--rarity-uncommon)',
    bloom: 6,
    label: 'Uncommon'
  },
  rare: {
    ink: 'var(--rarity-rare)',
    bloom: 14,
    label: 'Rare'
  },
  holo: {
    ink: 'var(--rarity-holo)',
    bloom: 22,
    label: 'Holo'
  },
  secret: {
    ink: 'var(--rarity-secret)',
    bloom: 34,
    label: 'Secret'
  }
};
function RarityBadge({
  rarity = 'common',
  showLabel = true,
  style
}) {
  const r = RARITY[rarity] || RARITY.common;
  return /*#__PURE__*/React.createElement("span", {
    "data-rarity": rarity,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-1) var(--space-2)',
      border: 'var(--border-width) solid ' + r.ink,
      color: r.ink,
      background: 'var(--void)',
      boxShadow: r.bloom ? '0 0 ' + r.bloom + 'px ' + r.ink : 'none',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      lineHeight: 1.4,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      width: '6px',
      height: '6px',
      background: r.ink,
      boxShadow: r.bloom ? '0 0 ' + Math.round(r.bloom / 2) + 'px ' + r.ink : 'none'
    }
  }), showLabel ? r.label : null);
}
Object.assign(__ds_scope, { RARITY, RarityBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/RarityBadge.jsx", error: String((e && e.message) || e) }); }

// components/cards/Scanlines.jsx
try { (() => {
function Scanlines({
  vignette = true,
  opacity = 1,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      ...style
    }
  }, children, /*#__PURE__*/React.createElement("div", {
    "aria-hidden": "true",
    style: {
      position: 'absolute',
      inset: 0,
      pointerEvents: 'none',
      zIndex: 60,
      opacity: opacity,
      backgroundImage: 'repeating-linear-gradient(180deg,rgba(17,7,31,.42) 0 1px,transparent 1px 3px)' + (vignette ? ',radial-gradient(120% 90% at 50% 45%,transparent 40%,var(--void) 100%)' : '')
    }
  }));
}
Object.assign(__ds_scope, { Scanlines });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/Scanlines.jsx", error: String((e && e.message) || e) }); }

// components/cards/StatFigure.jsx
try { (() => {
function StatFigure({
  label,
  value,
  unit,
  sign = 'none',
  size = 'md',
  style
}) {
  const ink = sign === 'positive' ? 'var(--lime)' : sign === 'negative' ? 'var(--red)' : sign === 'currency' ? 'var(--amber)' : 'var(--text-primary)';
  const fs = size === 'lg' ? '24px' : size === 'sm' ? 'var(--type-label)' : 'var(--type-data)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-1)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)'
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: fs,
      fontVariantNumeric: 'tabular-nums',
      fontWeight: 600,
      color: ink
    }
  }, sign === 'positive' ? '+' : sign === 'negative' ? '−' : '', value, unit && /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--text-muted)',
      fontSize: 'var(--type-label)',
      marginLeft: '4px'
    }
  }, unit)));
}
Object.assign(__ds_scope, { StatFigure });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/StatFigure.jsx", error: String((e && e.message) || e) }); }

// components/core/Badge.jsx
try { (() => {
const INKS = {
  neutral: 'var(--text-dim)',
  cyan: 'var(--cyan)',
  magenta: 'var(--magenta)',
  amber: 'var(--amber)',
  lime: 'var(--lime)',
  red: 'var(--red)'
};
function Badge({
  ink = 'neutral',
  solid = false,
  children,
  style
}) {
  const c = INKS[ink] || INKS.neutral;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-1)',
      padding: 'var(--space-1) var(--space-2)',
      borderRadius: 0,
      border: 'var(--border-width) solid ' + c,
      background: solid ? c : 'transparent',
      color: solid ? 'var(--text-on-fill)' : c,
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      lineHeight: 1.4,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Badge.jsx", error: String((e && e.message) || e) }); }

// components/cards/TradingCard.jsx
try { (() => {
const PIXEL_GRID = 'repeating-linear-gradient(0deg,rgba(167,148,212,.10) 0 1px,transparent 1px 8px),repeating-linear-gradient(90deg,rgba(167,148,212,.10) 0 1px,transparent 1px 8px)';
const FOIL = 'repeating-conic-gradient(from 0deg at 0 0,#FF3DA5 0% 25%,#4DE8F0 25% 50%)';
function TradingCard({
  name,
  cost,
  rarity = 'common',
  creatureType,
  badges = [],
  rules,
  setCode,
  collectorNumber,
  illustrator,
  art,
  width = 280,
  foil = false,
  onClick,
  style
}) {
  const r = __ds_scope.RARITY[rarity] || __ds_scope.RARITY.common;
  const showFoil = foil || rarity === 'holo' || rarity === 'secret';
  return /*#__PURE__*/React.createElement("article", {
    onClick: onClick,
    "data-rarity": rarity,
    style: {
      width: width,
      background: 'var(--screen)',
      border: 'var(--border-width) solid ' + r.ink,
      borderRadius: 0,
      boxShadow: 'var(--shadow-offset)' + (r.bloom ? ', 0 0 ' + r.bloom + 'px ' + r.ink : ''),
      cursor: onClick ? 'pointer' : 'default',
      display: 'flex',
      flexDirection: 'column',
      ...style
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-2)',
      padding: 'var(--space-2) var(--space-3)',
      background: 'var(--screen-lift)',
      borderBottom: 'var(--border-width) solid ' + r.ink
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-pixel-sm)',
      lineHeight: 1.5,
      color: rarity === 'secret' ? 'var(--amber)' : 'var(--text-primary)'
    }
  }, name), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      fontVariantNumeric: 'tabular-nums',
      color: 'var(--amber)',
      fontWeight: 600
    }
  }, cost)), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      aspectRatio: '4 / 3',
      background: 'var(--void)',
      borderBottom: 'var(--border-width) solid var(--bezel)',
      overflow: 'hidden'
    }
  }, art && /*#__PURE__*/React.createElement("img", {
    src: art,
    alt: "",
    style: {
      position: 'absolute',
      inset: 0,
      width: '100%',
      height: '100%',
      objectFit: 'cover'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      backgroundImage: PIXEL_GRID
    }
  }), showFoil && /*#__PURE__*/React.createElement("div", {
    "aria-hidden": "true",
    style: {
      position: 'absolute',
      inset: 0,
      mixBlendMode: 'screen',
      opacity: 0.35,
      backgroundImage: FOIL,
      backgroundSize: '12px 12px'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      flexWrap: 'wrap',
      padding: 'var(--space-2) var(--space-3)',
      background: 'var(--screen-lift)',
      borderBottom: 'var(--border-width) solid var(--bezel)'
    }
  }, creatureType && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-dim)'
    }
  }, creatureType), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      gap: 'var(--space-1)'
    }
  }, /*#__PURE__*/React.createElement(__ds_scope.RarityBadge, {
    rarity: rarity
  }), badges.slice(0, 2).map(b => /*#__PURE__*/React.createElement(__ds_scope.Badge, {
    key: b
  }, b)))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-3)',
      minHeight: '64px',
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--type-body)',
      lineHeight: 'var(--leading-body)',
      color: 'var(--text-dim)',
      flex: 1
    }
  }, rules), /*#__PURE__*/React.createElement("footer", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)',
      justifyContent: 'space-between',
      padding: 'var(--space-2) var(--space-3)',
      borderTop: 'var(--border-width) solid var(--bezel)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontVariantNumeric: 'tabular-nums'
    }
  }, setCode, " ", collectorNumber), /*#__PURE__*/React.createElement("span", null, illustrator)));
}
Object.assign(__ds_scope, { TradingCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/cards/TradingCard.jsx", error: String((e && e.message) || e) }); }

// components/core/Button.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const TONES = {
  primary: {
    fill: 'var(--cyan)',
    ink: 'var(--text-on-fill)',
    border: 'var(--cyan)'
  },
  secondary: {
    fill: 'var(--magenta)',
    ink: 'var(--text-on-fill)',
    border: 'var(--magenta)'
  },
  danger: {
    fill: 'var(--red)',
    ink: 'var(--text-on-fill)',
    border: 'var(--red)'
  },
  ghost: {
    fill: 'transparent',
    ink: 'var(--cyan)',
    border: 'var(--cyan)'
  },
  quiet: {
    fill: 'transparent',
    ink: 'var(--text-dim)',
    border: 'var(--bezel)'
  }
};
const SIZES = {
  sm: {
    pad: 'var(--space-1) var(--space-2)',
    font: 'var(--type-label)',
    fam: 'var(--font-data)',
    ls: 'var(--tracking-label)'
  },
  md: {
    pad: 'var(--space-2) var(--space-4)',
    font: 'var(--type-label)',
    fam: 'var(--font-data)',
    ls: 'var(--tracking-label)'
  },
  lg: {
    pad: 'var(--space-3) var(--space-6)',
    font: 'var(--type-title)',
    fam: 'var(--font-display)',
    ls: 'var(--tracking-display)'
  }
};
function Button({
  tone = 'primary',
  size = 'md',
  disabled = false,
  pressed = false,
  full = false,
  type = 'button',
  onClick,
  children,
  style,
  ...rest
}) {
  const t = TONES[tone] || TONES.primary,
    s = SIZES[size] || SIZES.md;
  const [down, setDown] = React.useState(false);
  const isDown = down || pressed;
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    onMouseDown: () => setDown(true),
    onMouseUp: () => setDown(false),
    onMouseLeave: () => setDown(false),
    style: {
      font: 'inherit',
      fontFamily: s.fam,
      fontSize: s.font,
      letterSpacing: s.ls,
      textTransform: 'uppercase',
      padding: s.pad,
      background: t.fill,
      color: t.ink,
      border: 'var(--border-width) solid ' + t.border,
      borderRadius: 0,
      cursor: disabled ? 'not-allowed' : 'pointer',
      display: full ? 'flex' : 'inline-flex',
      width: full ? '100%' : 'auto',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 'var(--space-2)',
      boxShadow: isDown ? 'none' : 'var(--shadow-offset)',
      transform: isDown ? 'translate(4px,4px)' : 'none',
      transition: 'transform var(--dur-fast) var(--ease-quantized),box-shadow var(--dur-fast) var(--ease-quantized),background var(--dur-slow) var(--ease-quantized)',
      opacity: disabled ? 0.4 : 1,
      filter: disabled ? 'grayscale(0.5)' : 'none',
      ...style
    }
  }, rest), children);
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Button.jsx", error: String((e && e.message) || e) }); }

// components/core/IconButton.jsx
try { (() => {
const BOX = {
  sm: '28px',
  md: '36px',
  lg: '44px'
};
function IconButton({
  tone = 'quiet',
  size = 'md',
  label,
  disabled = false,
  onClick,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement(__ds_scope.Button, {
    tone: tone,
    size: size,
    disabled: disabled,
    onClick: onClick,
    "aria-label": label,
    title: label,
    style: {
      width: BOX[size],
      height: BOX[size],
      padding: 0,
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { IconButton });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/IconButton.jsx", error: String((e && e.message) || e) }); }

// components/core/Panel.jsx
try { (() => {
function Panel({
  tone = 'screen',
  emphasis = false,
  inkEdge,
  title,
  label,
  footer,
  padding = 'var(--space-4)',
  children,
  style
}) {
  const bg = tone === 'lift' ? 'var(--screen-lift)' : tone === 'bezel' ? 'var(--bezel)' : 'var(--screen)';
  return /*#__PURE__*/React.createElement("section", {
    style: {
      background: bg,
      border: (emphasis ? 'var(--border-width-emph)' : 'var(--border-width)') + ' solid ' + (inkEdge || 'var(--bezel)'),
      borderRadius: 0,
      boxShadow: 'var(--shadow-offset)',
      ...style
    }
  }, (title || label) && /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-3)',
      padding: 'var(--space-3) var(--space-4)',
      borderBottom: 'var(--border-width) solid var(--bezel)'
    }
  }, title && /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-title)',
      color: 'var(--text-primary)'
    }
  }, title), label && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)'
    }
  }, label)), /*#__PURE__*/React.createElement("div", {
    style: {
      padding
    }
  }, children), footer && /*#__PURE__*/React.createElement("footer", {
    style: {
      padding: 'var(--space-3) var(--space-4)',
      borderTop: 'var(--border-width) solid var(--bezel)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)'
    }
  }, footer));
}
Object.assign(__ds_scope, { Panel });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Panel.jsx", error: String((e && e.message) || e) }); }

// components/core/Tag.jsx
try { (() => {
function Tag({
  children,
  onRemove,
  selected = false,
  onClick,
  style
}) {
  return /*#__PURE__*/React.createElement("span", {
    onClick: onClick,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      padding: 'var(--space-1) var(--space-2)',
      borderRadius: 0,
      cursor: onClick ? 'pointer' : 'default',
      border: 'var(--border-width) solid ' + (selected ? 'var(--cyan)' : 'var(--bezel)'),
      background: selected ? 'var(--screen-lift)' : 'var(--screen)',
      color: selected ? 'var(--cyan)' : 'var(--text-dim)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      transition: 'all var(--dur-fast) var(--ease-quantized)',
      ...style
    }
  }, children, onRemove && /*#__PURE__*/React.createElement("button", {
    onClick: e => {
      e.stopPropagation();
      onRemove();
    },
    "aria-label": "Remove",
    style: {
      background: 'none',
      border: 'none',
      color: 'inherit',
      cursor: 'pointer',
      padding: 0,
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      lineHeight: 1
    }
  }, "\xD7"));
}
Object.assign(__ds_scope, { Tag });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/Tag.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Dialog.jsx
try { (() => {
function Dialog({
  open = true,
  title,
  children,
  confirmLabel = 'OK',
  cancelLabel = 'Cancel',
  tone = 'primary',
  onConfirm,
  onCancel,
  width = '480px'
}) {
  if (!open) return null;
  return /*#__PURE__*/React.createElement("div", {
    role: "dialog",
    "aria-modal": "true",
    "aria-label": title,
    style: {
      position: 'absolute',
      inset: 0,
      display: 'grid',
      placeItems: 'center',
      padding: 'var(--space-8)',
      background: 'rgba(17,7,31,0.82)',
      zIndex: 100
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: width,
      maxWidth: '100%',
      background: 'var(--screen)',
      border: 'var(--border-width-emph) solid var(--cyan)',
      boxShadow: 'var(--shadow-offset-lg)'
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-4)',
      padding: 'var(--space-4)',
      borderBottom: 'var(--border-width) solid var(--bezel)',
      background: 'var(--screen-lift)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-title)',
      color: 'var(--cyan)'
    }
  }, title), /*#__PURE__*/React.createElement(__ds_scope.IconButton, {
    size: "sm",
    label: "Close",
    onClick: onCancel
  }, "\xD7")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-4)',
      color: 'var(--text-dim)'
    }
  }, children), /*#__PURE__*/React.createElement("footer", {
    style: {
      display: 'flex',
      justifyContent: 'flex-end',
      gap: 'var(--space-3)',
      padding: 'var(--space-4)',
      borderTop: 'var(--border-width) solid var(--bezel)'
    }
  }, cancelLabel && /*#__PURE__*/React.createElement(__ds_scope.Button, {
    tone: "quiet",
    onClick: onCancel
  }, cancelLabel), /*#__PURE__*/React.createElement(__ds_scope.Button, {
    tone: tone,
    onClick: onConfirm
  }, confirmLabel))));
}
Object.assign(__ds_scope, { Dialog });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Dialog.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Toast.jsx
try { (() => {
const INKS = {
  info: 'var(--cyan)',
  success: 'var(--lime)',
  warning: 'var(--amber)',
  danger: 'var(--red)'
};
function Toast({
  tone = 'info',
  title,
  children,
  onDismiss,
  style
}) {
  const c = INKS[tone] || INKS.info;
  return /*#__PURE__*/React.createElement("div", {
    role: "status",
    style: {
      display: 'flex',
      alignItems: 'flex-start',
      gap: 'var(--space-3)',
      background: 'var(--screen-lift)',
      border: 'var(--border-width) solid ' + c,
      borderLeft: 'var(--border-width-emph) solid ' + c,
      boxShadow: 'var(--shadow-offset)',
      padding: 'var(--space-3) var(--space-4)',
      minWidth: '280px',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-1)'
    }
  }, title && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: c
    }
  }, title), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--type-body)',
      lineHeight: 'var(--leading-body)',
      color: 'var(--text-primary)'
    }
  }, children)), onDismiss && /*#__PURE__*/React.createElement("button", {
    onClick: onDismiss,
    "aria-label": "Dismiss",
    style: {
      background: 'none',
      border: 'none',
      color: 'var(--text-muted)',
      cursor: 'pointer',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      padding: 0
    }
  }, "\xD7"));
}
Object.assign(__ds_scope, { Toast });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Toast.jsx", error: String((e && e.message) || e) }); }

// components/feedback/Tooltip.jsx
try { (() => {
function Tooltip({
  label,
  side = 'top',
  children,
  style
}) {
  const [on, setOn] = React.useState(false);
  const pos = side === 'bottom' ? {
    top: 'calc(100% + 8px)',
    left: '50%',
    transform: 'translateX(-50%)'
  } : side === 'left' ? {
    right: 'calc(100% + 8px)',
    top: '50%',
    transform: 'translateY(-50%)'
  } : side === 'right' ? {
    left: 'calc(100% + 8px)',
    top: '50%',
    transform: 'translateY(-50%)'
  } : {
    bottom: 'calc(100% + 8px)',
    left: '50%',
    transform: 'translateX(-50%)'
  };
  return /*#__PURE__*/React.createElement("span", {
    style: {
      position: 'relative',
      display: 'inline-flex',
      ...style
    },
    onMouseEnter: () => setOn(true),
    onMouseLeave: () => setOn(false),
    onFocus: () => setOn(true),
    onBlur: () => setOn(false)
  }, children, on && /*#__PURE__*/React.createElement("span", {
    role: "tooltip",
    style: {
      position: 'absolute',
      ...pos,
      zIndex: 80,
      whiteSpace: 'nowrap',
      background: 'var(--void)',
      border: 'var(--border-width) solid var(--cyan)',
      color: 'var(--text-primary)',
      boxShadow: 'var(--shadow-offset)',
      padding: 'var(--space-1) var(--space-2)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)'
    }
  }, label));
}
Object.assign(__ds_scope, { Tooltip });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/Tooltip.jsx", error: String((e && e.message) || e) }); }

// components/forms/Checkbox.jsx
try { (() => {
function Checkbox({
  checked = false,
  onChange,
  label,
  disabled = false,
  style
}) {
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.4 : 1,
      fontFamily: 'var(--font-ui)',
      fontSize: 'var(--type-body)',
      color: 'var(--text-primary)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: checked,
    disabled: disabled,
    onChange: e => onChange && onChange(e.target.checked),
    style: {
      position: 'absolute',
      opacity: 0,
      width: 0,
      height: 0
    }
  }), /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      width: '20px',
      height: '20px',
      flex: '0 0 20px',
      display: 'grid',
      placeItems: 'center',
      border: 'var(--border-width) solid ' + (checked ? 'var(--cyan)' : 'var(--bezel)'),
      background: checked ? 'var(--cyan)' : 'var(--void)',
      color: 'var(--text-on-fill)',
      fontFamily: 'var(--font-data)',
      fontSize: '12px',
      lineHeight: 1,
      transition: 'all var(--dur-fast) var(--ease-quantized)'
    }
  }, checked ? '✕' : ''), label);
}
Object.assign(__ds_scope, { Checkbox });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Checkbox.jsx", error: String((e && e.message) || e) }); }

// components/forms/Field.jsx
try { (() => {
function Field({
  label,
  hint,
  error,
  htmlFor,
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-2)',
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("label", {
    htmlFor: htmlFor,
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)'
    }
  }, label), children, (error || hint) && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: error ? 'var(--red)' : 'var(--text-muted)'
    }
  }, error || hint));
}
Object.assign(__ds_scope, { Field });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Field.jsx", error: String((e && e.message) || e) }); }

// components/forms/Input.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function Input({
  value,
  onChange,
  placeholder,
  type = 'text',
  mono = false,
  invalid = false,
  disabled = false,
  id,
  style,
  ...rest
}) {
  return /*#__PURE__*/React.createElement("input", _extends({
    id: id,
    type: type,
    value: value,
    placeholder: placeholder,
    disabled: disabled,
    onChange: onChange && (e => onChange(e.target.value)),
    style: {
      ...{
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--type-body)',
        color: 'var(--text-primary)',
        background: 'var(--void)',
        border: 'var(--border-width) solid var(--bezel)',
        borderRadius: 0,
        padding: 'var(--space-2) var(--space-3)',
        width: '100%',
        outlineOffset: 'var(--focus-ring-offset)'
      },
      fontFamily: mono ? 'var(--font-data)' : 'var(--font-ui)',
      fontSize: mono ? 'var(--type-data)' : 'var(--type-body)',
      fontVariantNumeric: mono ? 'tabular-nums' : 'normal',
      borderColor: invalid ? 'var(--red)' : 'var(--bezel)',
      opacity: disabled ? 0.4 : 1,
      ...style
    }
  }, rest));
}
Object.assign(__ds_scope, { Input });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Input.jsx", error: String((e && e.message) || e) }); }

// components/forms/Radio.jsx
try { (() => {
function Radio({
  options = [],
  value,
  onChange,
  name = 'radio',
  disabled = false,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    role: "radiogroup",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-2)',
      ...style
    }
  }, options.map(o => {
    const v = typeof o === 'string' ? o : o.value,
      l = typeof o === 'string' ? o : o.label,
      on = v === value;
    return /*#__PURE__*/React.createElement("label", {
      key: v,
      style: {
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--type-body)'
      }
    }, /*#__PURE__*/React.createElement("input", {
      type: "radio",
      name: name,
      checked: on,
      disabled: disabled,
      onChange: () => onChange && onChange(v),
      style: {
        position: 'absolute',
        opacity: 0,
        width: 0,
        height: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      "aria-hidden": "true",
      style: {
        width: '20px',
        height: '20px',
        flex: '0 0 20px',
        display: 'grid',
        placeItems: 'center',
        border: 'var(--border-width) solid ' + (on ? 'var(--cyan)' : 'var(--bezel)'),
        background: 'var(--void)'
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: '8px',
        height: '8px',
        background: on ? 'var(--cyan)' : 'transparent'
      }
    })), l);
  }));
}
Object.assign(__ds_scope, { Radio });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Radio.jsx", error: String((e && e.message) || e) }); }

// components/forms/Select.jsx
try { (() => {
function Select({
  value,
  onChange,
  options = [],
  disabled = false,
  id,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      ...style
    }
  }, /*#__PURE__*/React.createElement("select", {
    id: id,
    value: value,
    disabled: disabled,
    onChange: onChange && (e => onChange(e.target.value)),
    style: {
      ...{
        fontFamily: 'var(--font-ui)',
        fontSize: 'var(--type-body)',
        color: 'var(--text-primary)',
        background: 'var(--void)',
        border: 'var(--border-width) solid var(--bezel)',
        borderRadius: 0,
        padding: 'var(--space-2) var(--space-3)',
        width: '100%',
        outlineOffset: 'var(--focus-ring-offset)'
      },
      appearance: 'none',
      paddingRight: 'var(--space-8)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      textTransform: 'uppercase',
      letterSpacing: '0.06em',
      cursor: 'pointer',
      opacity: disabled ? 0.4 : 1
    }
  }, options.map(o => {
    const v = typeof o === 'string' ? o : o.value,
      l = typeof o === 'string' ? o : o.label;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v,
      style: {
        background: 'var(--screen)'
      }
    }, l);
  })), /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      position: 'absolute',
      right: 'var(--space-3)',
      top: '50%',
      transform: 'translateY(-50%)',
      color: 'var(--cyan)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      pointerEvents: 'none'
    }
  }, "\u25BC"));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Select.jsx", error: String((e && e.message) || e) }); }

// components/forms/Switch.jsx
try { (() => {
function Switch({
  checked = false,
  onChange,
  label,
  disabled = false,
  style
}) {
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 'var(--space-3)',
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.4 : 1,
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-dim)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    role: "switch",
    checked: checked,
    disabled: disabled,
    onChange: e => onChange && onChange(e.target.checked),
    style: {
      position: 'absolute',
      opacity: 0,
      width: 0,
      height: 0
    }
  }), /*#__PURE__*/React.createElement("span", {
    "aria-hidden": "true",
    style: {
      width: '44px',
      height: '22px',
      flex: '0 0 44px',
      padding: '2px',
      display: 'flex',
      justifyContent: checked ? 'flex-end' : 'flex-start',
      border: 'var(--border-width) solid ' + (checked ? 'var(--lime)' : 'var(--bezel)'),
      background: 'var(--void)',
      transition: 'all var(--dur-slow) var(--ease-quantized)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: '16px',
      height: '14px',
      background: checked ? 'var(--lime)' : 'var(--text-muted)'
    }
  })), label);
}
Object.assign(__ds_scope, { Switch });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/Switch.jsx", error: String((e && e.message) || e) }); }

// components/navigation/Tabs.jsx
try { (() => {
function Tabs({
  tabs = [],
  value,
  onChange,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    role: "tablist",
    style: {
      display: 'flex',
      gap: 'var(--space-1)',
      borderBottom: 'var(--border-width) solid var(--bezel)',
      ...style
    }
  }, tabs.map(t => {
    const v = typeof t === 'string' ? t : t.value,
      l = typeof t === 'string' ? t : t.label,
      on = v === value;
    return /*#__PURE__*/React.createElement("button", {
      key: v,
      role: "tab",
      "aria-selected": on,
      onClick: () => onChange && onChange(v),
      style: {
        background: on ? 'var(--screen-lift)' : 'transparent',
        border: 'var(--border-width) solid ' + (on ? 'var(--bezel)' : 'transparent'),
        borderBottom: 'none',
        color: on ? 'var(--cyan)' : 'var(--text-muted)',
        cursor: 'pointer',
        padding: 'var(--space-2) var(--space-4)',
        marginBottom: '-2px',
        fontFamily: 'var(--font-data)',
        fontSize: 'var(--type-label)',
        textTransform: 'uppercase',
        letterSpacing: 'var(--tracking-label)',
        boxShadow: on ? 'inset 0 -3px 0 var(--cyan)' : 'none',
        transition: 'all var(--dur-fast) var(--ease-quantized)'
      }
    }, l);
  }));
}
Object.assign(__ds_scope, { Tabs });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigation/Tabs.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/AppShell.jsx
try { (() => {
function TopBar({
  tab,
  onTab,
  query,
  onQuery
}) {
  const {
    Input,
    IconButton,
    Badge
  } = window.CRTArcadeDesignSystem_70e231;
  return /*#__PURE__*/React.createElement("header", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-6)',
      padding: 'var(--space-3) var(--space-6)',
      background: 'var(--screen-lift)',
      borderBottom: 'var(--border-width-emph) solid var(--bezel)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-title)',
      color: 'var(--cyan)',
      textShadow: '0 0 14px rgba(77,232,240,.55)',
      whiteSpace: 'nowrap'
    }
  }, "CRT ARCADE"), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: 'flex',
      gap: 'var(--space-1)'
    }
  }, ['BROWSE', 'DECK', 'PRICES'].map(t => /*#__PURE__*/React.createElement("button", {
    key: t,
    onClick: () => onTab(t),
    style: {
      background: tab === t ? 'var(--screen)' : 'transparent',
      border: 'var(--border-width) solid ' + (tab === t ? 'var(--cyan)' : 'transparent'),
      color: tab === t ? 'var(--cyan)' : 'var(--text-muted)',
      cursor: 'pointer',
      padding: 'var(--space-2) var(--space-4)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)'
    }
  }, t))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      maxWidth: '320px'
    }
  }, /*#__PURE__*/React.createElement(Input, {
    type: "search",
    mono: true,
    value: query,
    onChange: onQuery,
    placeholder: "SEARCH CARDS"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: 'auto',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-3)'
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    ink: "amber"
  }, "CREDITS 12"), /*#__PURE__*/React.createElement(IconButton, {
    label: "Notifications",
    tone: "quiet"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "bell"
  })), /*#__PURE__*/React.createElement(IconButton, {
    label: "Account",
    tone: "quiet"
  }, /*#__PURE__*/React.createElement("i", {
    "data-lucide": "user"
  }))));
}
function FilterRail({
  filters,
  onToggle,
  rarity,
  onRarity
}) {
  const {
    Panel,
    Tag,
    Checkbox,
    Select,
    Field,
    RarityBadge
  } = window.CRTArcadeDesignSystem_70e231;
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: '240px',
      flex: '0 0 240px',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "FILTERS",
    label: String(filters.length) + ' on',
    padding: "var(--space-4)"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement(Field, {
    label: "Set"
  }, /*#__PURE__*/React.createElement(Select, {
    options: ['ALL SETS', 'NEON DRIFT', 'VOID CIRCUIT'],
    value: "ALL SETS"
  })), /*#__PURE__*/React.createElement(Field, {
    label: "Rarity"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-2)'
    }
  }, ['common', 'uncommon', 'rare', 'holo', 'secret'].map(r => /*#__PURE__*/React.createElement("label", {
    key: r,
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-2)',
      cursor: 'pointer'
    }
  }, /*#__PURE__*/React.createElement(Checkbox, {
    checked: rarity.includes(r),
    onChange: () => onRarity(r)
  }), /*#__PURE__*/React.createElement(RarityBadge, {
    rarity: r
  }))))), /*#__PURE__*/React.createElement(Field, {
    label: "Quick"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)',
      flexWrap: 'wrap'
    }
  }, ['Owned', 'Foil', 'Under $20'].map(t => /*#__PURE__*/React.createElement(Tag, {
    key: t,
    selected: filters.includes(t),
    onClick: () => onToggle(t)
  }, t)))))));
}
Object.assign(window, {
  TopBar,
  FilterRail
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/AppShell.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/BrowseScreen.jsx
try { (() => {
function BrowseScreen({
  cards,
  onOpen,
  filters,
  onToggle,
  rarity,
  onRarity,
  sort,
  onSort
}) {
  const {
    TradingCard,
    Select,
    Panel,
    StatFigure
  } = window.CRTArcadeDesignSystem_70e231;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-6)',
      padding: 'var(--space-6)',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement(FilterRail, {
    filters: filters,
    onToggle: onToggle,
    rarity: rarity,
    onRarity: onRarity
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-marquee)',
      color: 'var(--text-primary)'
    }
  }, "CARD INDEX"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement(StatFigure, {
    label: "Results",
    value: cards.length
  }), /*#__PURE__*/React.createElement(Select, {
    value: sort,
    onChange: onSort,
    options: ['NAME A–Z', 'PRICE HIGH', 'RARITY', 'EV'],
    style: {
      width: '180px'
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))',
      gap: 'var(--space-6)'
    }
  }, cards.map(c => /*#__PURE__*/React.createElement(TradingCard, {
    key: c.id,
    width: "100%",
    name: c.name,
    cost: c.cost,
    rarity: c.rarity,
    creatureType: c.type,
    badges: c.owned ? ['Owned ' + c.owned] : [],
    rules: c.rules,
    setCode: c.set,
    collectorNumber: c.num,
    illustrator: c.ill,
    onClick: () => onOpen(c)
  }))), cards.length === 0 && /*#__PURE__*/React.createElement(Panel, {
    padding: "var(--space-8)"
  }, /*#__PURE__*/React.createElement("span", {
    className: "crt-label"
  }, "No cards match these filters"))));
}
Object.assign(window, {
  BrowseScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/BrowseScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/CardDetailScreen.jsx
try { (() => {
function CardDetailScreen({
  card,
  onBack,
  onAdd,
  onScrap
}) {
  const {
    TradingCard,
    Panel,
    Button,
    StatFigure,
    RarityBadge,
    Badge,
    Tabs,
    Tooltip
  } = window.CRTArcadeDesignSystem_70e231;
  const [tab, setTab] = React.useState('PRICE HISTORY');
  const bars = [12, 14, 13, 16, 15, 18, 17, 21, 19, 22, 24, 23];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-6)',
      display: 'flex',
      gap: 'var(--space-8)',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      flex: '0 0 300px'
    }
  }, /*#__PURE__*/React.createElement(Button, {
    tone: "quiet",
    size: "sm",
    onClick: onBack
  }, "\u2190 Back to index"), /*#__PURE__*/React.createElement(TradingCard, {
    width: 300,
    name: card.name,
    cost: card.cost,
    rarity: card.rarity,
    creatureType: card.type,
    badges: ['Standard'],
    rules: card.rules,
    setCode: card.set,
    collectorNumber: card.num,
    illustrator: card.ill
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--space-4)',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-marquee)'
    }
  }, card.name), /*#__PURE__*/React.createElement(RarityBadge, {
    rarity: card.rarity
  }), /*#__PURE__*/React.createElement(Badge, {
    ink: "lime"
  }, "Legal")), /*#__PURE__*/React.createElement(Panel, {
    title: "MARKET",
    label: card.set + ' ' + card.num
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-8)',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(StatFigure, {
    label: "Market",
    value: card.price.toFixed(2),
    sign: "currency",
    size: "lg"
  }), /*#__PURE__*/React.createElement(StatFigure, {
    label: "EV / pack",
    value: Math.abs(card.ev).toFixed(2),
    sign: card.ev >= 0 ? 'positive' : 'negative',
    size: "lg"
  }), /*#__PURE__*/React.createElement(StatFigure, {
    label: "Owned",
    value: card.owned,
    size: "lg"
  }), /*#__PURE__*/React.createElement(StatFigure, {
    label: "7d change",
    value: "4.2",
    unit: "%",
    sign: "positive",
    size: "lg"
  }))), /*#__PURE__*/React.createElement(Panel, {
    padding: "0"
  }, /*#__PURE__*/React.createElement(Tabs, {
    tabs: ['PRICE HISTORY', 'RULINGS', 'PRINTINGS'],
    value: tab,
    onChange: setTab,
    style: {
      padding: '0 var(--space-4)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-4)'
    }
  }, tab === 'PRICE HISTORY' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      gap: 'var(--space-2)',
      height: '120px'
    }
  }, bars.map((b, i) => /*#__PURE__*/React.createElement(Tooltip, {
    key: i,
    label: '$' + (b + card.price - 24).toFixed(2)
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'block',
      width: '24px',
      height: b * 5 + 'px',
      background: i === bars.length - 1 ? 'var(--cyan)' : 'var(--bezel)'
    }
  })))), tab === 'RULINGS' && /*#__PURE__*/React.createElement("p", {
    style: {
      color: 'var(--text-dim)'
    }
  }, "Damage from this ability is dealt before the tapped unit untaps. If no unit is tapped, the ability does nothing."), tab === 'PRINTINGS' && /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-2)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      fontVariantNumeric: 'tabular-nums',
      color: 'var(--text-dim)'
    }
  }, /*#__PURE__*/React.createElement("span", null, "NDR 045/180 \u2014 REGULAR \u2014 $18.40"), /*#__PURE__*/React.createElement("span", null, "NDR 171/180 \u2014 FOIL \u2014 $64.00"), /*#__PURE__*/React.createElement("span", null, "VCR 004/144 \u2014 REPRINT \u2014 $11.75")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-3)'
    }
  }, /*#__PURE__*/React.createElement(Button, {
    tone: "primary",
    onClick: onAdd
  }, "Add to deck"), /*#__PURE__*/React.createElement(Button, {
    tone: "secondary"
  }, "Trade"), /*#__PURE__*/React.createElement(Button, {
    tone: "danger",
    onClick: onScrap
  }, "Scrap copy"))));
}
Object.assign(window, {
  CardDetailScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/CardDetailScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/DeckBuilderScreen.jsx
try { (() => {
function DeckBuilderScreen({
  deck,
  cards,
  onQty,
  onOpen
}) {
  const {
    Panel,
    Button,
    StatFigure,
    Badge,
    RarityBadge,
    Input,
    Field,
    Switch,
    IconButton
  } = window.CRTArcadeDesignSystem_70e231;
  const byId = Object.fromEntries(cards.map(c => [c.id, c]));
  const legal = deck.count <= deck.limit;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-6)',
      display: 'flex',
      gap: 'var(--space-6)',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)',
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-marquee)'
    }
  }, deck.name), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-3)'
    }
  }, /*#__PURE__*/React.createElement(Button, {
    tone: "ghost",
    size: "sm"
  }, "Export list"), /*#__PURE__*/React.createElement(Button, {
    tone: "primary",
    size: "sm"
  }, "Save deck"))), /*#__PURE__*/React.createElement(Panel, {
    title: "DECK LIST",
    label: deck.count + ' / ' + deck.limit,
    padding: "0",
    inkEdge: legal ? 'var(--bezel)' : 'var(--red)',
    emphasis: !legal
  }, /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      fontVariantNumeric: 'tabular-nums'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, ['QTY', 'CARD', 'TYPE', 'RARITY', 'MARKET', ''].map(h => /*#__PURE__*/React.createElement("th", {
    key: h,
    style: {
      textAlign: h === 'MARKET' ? 'right' : 'left',
      padding: 'var(--space-2) var(--space-4)',
      borderBottom: 'var(--border-width) solid var(--bezel)',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)',
      fontWeight: 400
    }
  }, h)))), /*#__PURE__*/React.createElement("tbody", null, deck.entries.map(e => {
    const c = byId[e.id];
    return /*#__PURE__*/React.createElement("tr", {
      key: e.id,
      style: {
        borderBottom: 'var(--border-width) solid var(--screen-lift)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        color: 'var(--amber)',
        fontWeight: 600
      }
    }, e.qty, "\xD7"), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onOpen(c),
      style: {
        background: 'none',
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        color: 'var(--cyan)',
        fontFamily: 'var(--font-display)',
        fontSize: 'var(--type-pixel-sm)'
      }
    }, c.name)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        color: 'var(--text-dim)'
      }
    }, c.type), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)'
      }
    }, /*#__PURE__*/React.createElement(RarityBadge, {
      rarity: c.rarity
    })), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        textAlign: 'right',
        color: 'var(--text-primary)'
      }
    }, (c.price * e.qty).toFixed(2)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)'
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 'var(--space-1)'
      }
    }, /*#__PURE__*/React.createElement(IconButton, {
      size: "sm",
      label: "Remove one",
      onClick: () => onQty(e.id, -1)
    }, "\u2212"), /*#__PURE__*/React.createElement(IconButton, {
      size: "sm",
      label: "Add one",
      tone: "ghost",
      onClick: () => onQty(e.id, 1)
    }, "+"))));
  }))))), /*#__PURE__*/React.createElement("aside", {
    style: {
      width: '280px',
      flex: '0 0 280px',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement(Panel, {
    title: "STATS",
    label: deck.format
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-6)'
    }
  }, /*#__PURE__*/React.createElement(StatFigure, {
    label: "Cards",
    value: deck.count,
    size: "lg"
  }), /*#__PURE__*/React.createElement(StatFigure, {
    label: "Value",
    value: deck.value.toFixed(2),
    sign: "currency",
    size: "lg"
  })), /*#__PURE__*/React.createElement(StatFigure, {
    label: "Win rate (30d)",
    value: deck.winRate.toFixed(1),
    unit: "%",
    sign: "positive"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    ink: legal ? 'lime' : 'red',
    solid: !legal
  }, legal ? 'Legal' : 'Illegal'), /*#__PURE__*/React.createElement(Badge, {
    ink: "cyan"
  }, deck.format)))), /*#__PURE__*/React.createElement(Panel, {
    title: "CURVE",
    label: "Cost"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      gap: 'var(--space-2)',
      height: '96px'
    }
  }, [2, 6, 9, 12, 8, 5, 3, 1].map((n, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 'var(--space-1)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: '100%',
      height: n * 7 + 'px',
      background: 'var(--magenta)'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-label)',
      color: 'var(--text-muted)'
    }
  }, i + 1))))), /*#__PURE__*/React.createElement(Panel, {
    title: "OPTIONS"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-3)'
    }
  }, /*#__PURE__*/React.createElement(Field, {
    label: "Deck name"
  }, /*#__PURE__*/React.createElement(Input, {
    value: deck.name
  })), /*#__PURE__*/React.createElement(Switch, {
    checked: true,
    label: "Public list"
  }), /*#__PURE__*/React.createElement(Switch, {
    checked: false,
    label: "Foil pricing"
  })))));
}
Object.assign(window, {
  DeckBuilderScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/DeckBuilderScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/PricesScreen.jsx
try { (() => {
function PricesScreen({
  cards,
  onOpen
}) {
  const {
    Panel,
    StatFigure,
    RarityBadge,
    Tabs,
    Select,
    Badge,
    Tooltip
  } = window.CRTArcadeDesignSystem_70e231;
  const [tab, setTab] = React.useState('MOVERS');
  return /*#__PURE__*/React.createElement("div", {
    style: {
      padding: 'var(--space-6)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 'var(--space-4)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: 'var(--font-display)',
      fontSize: 'var(--type-marquee)'
    }
  }, "PRICE FEED"), /*#__PURE__*/React.createElement(Select, {
    value: "LAST 7 DAYS",
    options: ['LAST 24 HOURS', 'LAST 7 DAYS', 'LAST 30 DAYS'],
    style: {
      width: '200px'
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(4,1fr)',
      gap: 'var(--space-4)'
    }
  }, [['Index', '1,204.00', 'currency'], ['Pack EV', '2.15', 'positive'], ['Spread', '0.80', 'negative'], ['Sealed stock', '412', 'none']].map(([l, v, s]) => /*#__PURE__*/React.createElement(Panel, {
    key: l,
    padding: "var(--space-4)"
  }, /*#__PURE__*/React.createElement(StatFigure, {
    label: l,
    value: v,
    sign: s,
    size: "lg"
  })))), /*#__PURE__*/React.createElement(Panel, {
    padding: "0"
  }, /*#__PURE__*/React.createElement(Tabs, {
    tabs: ['MOVERS', 'WATCHLIST', 'SEALED'],
    value: tab,
    onChange: setTab,
    style: {
      padding: '0 var(--space-4)'
    }
  }), /*#__PURE__*/React.createElement("table", {
    style: {
      width: '100%',
      borderCollapse: 'collapse',
      fontFamily: 'var(--font-data)',
      fontSize: 'var(--type-data)',
      fontVariantNumeric: 'tabular-nums'
    }
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, ['CARD', 'SET', 'RARITY', 'MARKET', '24H', 'EV'].map((h, i) => /*#__PURE__*/React.createElement("th", {
    key: h,
    style: {
      textAlign: i > 2 ? 'right' : 'left',
      padding: 'var(--space-2) var(--space-4)',
      borderBottom: 'var(--border-width) solid var(--bezel)',
      fontSize: 'var(--type-label)',
      textTransform: 'uppercase',
      letterSpacing: 'var(--tracking-label)',
      color: 'var(--text-muted)',
      fontWeight: 400
    }
  }, h)))), /*#__PURE__*/React.createElement("tbody", null, cards.map((c, i) => {
    const chg = (c.ev * 3.1 % 9).toFixed(1);
    const up = c.ev >= 0;
    return /*#__PURE__*/React.createElement("tr", {
      key: c.id,
      style: {
        borderBottom: 'var(--border-width) solid var(--screen-lift)',
        background: i % 2 ? 'transparent' : 'rgba(39,22,80,.4)'
      }
    }, /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)'
      }
    }, /*#__PURE__*/React.createElement("button", {
      onClick: () => onOpen(c),
      style: {
        background: 'none',
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        color: 'var(--cyan)',
        fontFamily: 'var(--font-display)',
        fontSize: 'var(--type-pixel-sm)'
      }
    }, c.name)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        color: 'var(--text-dim)'
      }
    }, c.set, " ", c.num), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)'
      }
    }, /*#__PURE__*/React.createElement(RarityBadge, {
      rarity: c.rarity
    })), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        textAlign: 'right',
        color: 'var(--amber)'
      }
    }, c.price.toFixed(2)), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        textAlign: 'right',
        color: up ? 'var(--lime)' : 'var(--red)'
      }
    }, up ? '+' : '−', Math.abs(chg), "%"), /*#__PURE__*/React.createElement("td", {
      style: {
        padding: 'var(--space-2) var(--space-4)',
        textAlign: 'right'
      }
    }, /*#__PURE__*/React.createElement(Tooltip, {
      label: "Expected value per pack",
      side: "left"
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: c.ev >= 0 ? 'var(--lime)' : 'var(--red)'
      }
    }, c.ev >= 0 ? '+' : '−', Math.abs(c.ev).toFixed(2)))));
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--space-2)'
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    ink: "cyan"
  }, "Feed live"), /*#__PURE__*/React.createElement(Badge, null, "Updated 12:04")));
}
Object.assign(window, {
  PricesScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/PricesScreen.jsx", error: String((e && e.message) || e) }); }

// ui_kits/cabinet/data.js
try { (() => {
window.CABINET_DATA = {
  cards: [{
    id: 'ndr-045',
    name: 'VOLT WYRM',
    cost: 4,
    rarity: 'rare',
    type: 'Beast — Circuit',
    rules: 'On play: deal 2 damage to a tapped unit.',
    set: 'NDR',
    num: '045/180',
    ill: 'ILL. K. MORO',
    price: 18.40,
    ev: 2.15,
    owned: 3
  }, {
    id: 'ndr-171',
    name: 'HOLO DRIFTER',
    cost: 6,
    rarity: 'holo',
    type: 'Spirit — Neon',
    rules: 'While this is in play, your packs cost 1 less.',
    set: 'NDR',
    num: '171/180',
    ill: 'ILL. J. VANE',
    price: 64.00,
    ev: 5.80,
    owned: 1
  }, {
    id: 'ndr-180',
    name: 'SECRET PRISM',
    cost: 9,
    rarity: 'secret',
    type: 'Artifact',
    rules: 'Secret rare. Burns brightest.',
    set: 'NDR',
    num: '180/180',
    ill: 'ILL. R. ASH',
    price: 212.50,
    ev: 9.05,
    owned: 0
  }, {
    id: 'ndr-012',
    name: 'COIN SLOT',
    cost: 1,
    rarity: 'common',
    type: 'Item — Token',
    rules: 'Gain 1 resource. Draw a card if you control a Circuit.',
    set: 'NDR',
    num: '012/180',
    ill: 'ILL. M. TAN',
    price: 0.25,
    ev: -0.10,
    owned: 12
  }, {
    id: 'ndr-088',
    name: 'PIXEL HOUND',
    cost: 3,
    rarity: 'uncommon',
    type: 'Beast — Static',
    rules: 'Whenever a card is scrapped, this gains 1 power.',
    set: 'NDR',
    num: '088/180',
    ill: 'ILL. S. OKI',
    price: 2.10,
    ev: 0.40,
    owned: 6
  }, {
    id: 'vcr-004',
    name: 'BEZEL KNIGHT',
    cost: 5,
    rarity: 'rare',
    type: 'Unit — Frame',
    rules: 'Adjacent units take 1 less damage.',
    set: 'VCR',
    num: '004/144',
    ill: 'ILL. D. LUME',
    price: 11.75,
    ev: 1.30,
    owned: 2
  }, {
    id: 'vcr-101',
    name: 'SCANLINE MAGE',
    cost: 2,
    rarity: 'uncommon',
    type: 'Unit — Signal',
    rules: 'Tap: reveal the top card of your deck.',
    set: 'VCR',
    num: '101/144',
    ill: 'ILL. P. RHO',
    price: 1.60,
    ev: 0.15,
    owned: 4
  }, {
    id: 'vcr-140',
    name: 'VOID CIRCUIT',
    cost: 8,
    rarity: 'holo',
    type: 'Terrain',
    rules: 'Units you control cannot be targeted by Signal effects.',
    set: 'VCR',
    num: '140/144',
    ill: 'ILL. A. KESS',
    price: 48.00,
    ev: 4.20,
    owned: 0
  }],
  deck: {
    name: 'VOLTAGE RUSH',
    format: 'STANDARD',
    count: 57,
    limit: 60,
    value: 184.20,
    winRate: 61.4,
    entries: [{
      id: 'ndr-045',
      qty: 4
    }, {
      id: 'ndr-012',
      qty: 8
    }, {
      id: 'ndr-088',
      qty: 4
    }, {
      id: 'vcr-004',
      qty: 3
    }, {
      id: 'vcr-101',
      qty: 4
    }]
  }
};
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/cabinet/data.js", error: String((e && e.message) || e) }); }

__ds_ns.RARITY = __ds_scope.RARITY;

__ds_ns.RarityBadge = __ds_scope.RarityBadge;

__ds_ns.Scanlines = __ds_scope.Scanlines;

__ds_ns.StatFigure = __ds_scope.StatFigure;

__ds_ns.TradingCard = __ds_scope.TradingCard;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.Button = __ds_scope.Button;

__ds_ns.IconButton = __ds_scope.IconButton;

__ds_ns.Panel = __ds_scope.Panel;

__ds_ns.Tag = __ds_scope.Tag;

__ds_ns.Dialog = __ds_scope.Dialog;

__ds_ns.Toast = __ds_scope.Toast;

__ds_ns.Tooltip = __ds_scope.Tooltip;

__ds_ns.Checkbox = __ds_scope.Checkbox;

__ds_ns.Field = __ds_scope.Field;

__ds_ns.Input = __ds_scope.Input;

__ds_ns.Radio = __ds_scope.Radio;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.Switch = __ds_scope.Switch;

__ds_ns.Tabs = __ds_scope.Tabs;

})();
