export type FileCategory =
  | 'code'
  | 'markup'
  | 'stylesheet'
  | 'config'
  | 'data'
  | 'documentation'
  | 'image'
  | 'document'
  | 'media'
  | 'archive'
  | 'text';

export interface ResolvedFileType {
  /** Normalized identifier e.g. 'rust', 'markdown', 'html', 'tiff', 'jpeg', 'pdf' */
  id: string;
  /** Human-readable display label e.g. 'Rust', 'Markdown', 'HTML', 'TIFF Image', 'JPEG Image', 'PDF Document' */
  label: string;
  /** Semantic category for icon & viewer handling */
  category: FileCategory;
  /** Normalized lowercase extension without dot, or '' if extensionless */
  extension: string;
  /** True when binary/media/document that cannot be syntax-highlighted as plain text */
  isBinaryOrMedia: boolean;
}

interface FileTypeSpec {
  id: string;
  label: string;
  category: FileCategory;
  isBinaryOrMedia: boolean;
}

const BASENAME_MAP: Record<string, FileTypeSpec> = {
  dockerfile: { id: 'dockerfile', label: 'Dockerfile', category: 'config', isBinaryOrMedia: false },
  containerfile: { id: 'dockerfile', label: 'Dockerfile', category: 'config', isBinaryOrMedia: false },
  makefile: { id: 'makefile', label: 'Makefile', category: 'config', isBinaryOrMedia: false },
  gnumakefile: { id: 'makefile', label: 'Makefile', category: 'config', isBinaryOrMedia: false },
  'cmakelists.txt': { id: 'cmake', label: 'CMake', category: 'config', isBinaryOrMedia: false },
  procfile: { id: 'procfile', label: 'Procfile', category: 'config', isBinaryOrMedia: false },
  rakefile: { id: 'ruby', label: 'Ruby', category: 'code', isBinaryOrMedia: false },
  gemfile: { id: 'ruby', label: 'Ruby', category: 'code', isBinaryOrMedia: false },
  jenkinsfile: { id: 'groovy', label: 'Groovy', category: 'code', isBinaryOrMedia: false },
  justfile: { id: 'just', label: 'Justfile', category: 'config', isBinaryOrMedia: false },
  '.gitignore': { id: 'gitignore', label: 'Git Ignore', category: 'config', isBinaryOrMedia: false },
  '.gitattributes': { id: 'gitattributes', label: 'Git Attributes', category: 'config', isBinaryOrMedia: false },
  '.gitmodules': { id: 'gitmodules', label: 'Git Modules', category: 'config', isBinaryOrMedia: false },
  '.dockerignore': { id: 'dockerignore', label: 'Docker Ignore', category: 'config', isBinaryOrMedia: false },
  '.npmrc': { id: 'npmrc', label: 'npm Config', category: 'config', isBinaryOrMedia: false },
  '.yarnrc': { id: 'yarnrc', label: 'Yarn Config', category: 'config', isBinaryOrMedia: false },
  '.editorconfig': { id: 'editorconfig', label: 'EditorConfig', category: 'config', isBinaryOrMedia: false },
  '.env': { id: 'dotenv', label: 'Env Config', category: 'config', isBinaryOrMedia: false },
};

const EXTENSION_MAP: Record<string, FileTypeSpec> = {
  // Explicitly mandated R2 extensions
  md: { id: 'markdown', label: 'Markdown', category: 'documentation', isBinaryOrMedia: false },
  html: { id: 'html', label: 'HTML', category: 'markup', isBinaryOrMedia: false },
  tiff: { id: 'tiff', label: 'TIFF Image', category: 'image', isBinaryOrMedia: true },
  tif: { id: 'tiff', label: 'TIFF Image', category: 'image', isBinaryOrMedia: true },
  jpeg: { id: 'jpeg', label: 'JPEG Image', category: 'image', isBinaryOrMedia: true },
  jpg: { id: 'jpeg', label: 'JPEG Image', category: 'image', isBinaryOrMedia: true },
  pdf: { id: 'pdf', label: 'PDF Document', category: 'document', isBinaryOrMedia: true },
  rs: { id: 'rust', label: 'Rust', category: 'code', isBinaryOrMedia: false },

  // Programming
  ts: { id: 'typescript', label: 'TypeScript', category: 'code', isBinaryOrMedia: false },
  mts: { id: 'typescript', label: 'TypeScript', category: 'code', isBinaryOrMedia: false },
  cts: { id: 'typescript', label: 'TypeScript', category: 'code', isBinaryOrMedia: false },
  tsx: { id: 'tsx', label: 'TSX', category: 'code', isBinaryOrMedia: false },
  js: { id: 'javascript', label: 'JavaScript', category: 'code', isBinaryOrMedia: false },
  mjs: { id: 'javascript', label: 'JavaScript', category: 'code', isBinaryOrMedia: false },
  cjs: { id: 'javascript', label: 'JavaScript', category: 'code', isBinaryOrMedia: false },
  jsx: { id: 'jsx', label: 'JSX', category: 'code', isBinaryOrMedia: false },
  py: { id: 'python', label: 'Python', category: 'code', isBinaryOrMedia: false },
  pyw: { id: 'python', label: 'Python', category: 'code', isBinaryOrMedia: false },
  pyi: { id: 'python', label: 'Python', category: 'code', isBinaryOrMedia: false },
  go: { id: 'go', label: 'Go', category: 'code', isBinaryOrMedia: false },
  java: { id: 'java', label: 'Java', category: 'code', isBinaryOrMedia: false },
  c: { id: 'c', label: 'C', category: 'code', isBinaryOrMedia: false },
  h: { id: 'c', label: 'C/C++ Header', category: 'code', isBinaryOrMedia: false },
  cpp: { id: 'cpp', label: 'C++', category: 'code', isBinaryOrMedia: false },
  cc: { id: 'cpp', label: 'C++', category: 'code', isBinaryOrMedia: false },
  cxx: { id: 'cpp', label: 'C++', category: 'code', isBinaryOrMedia: false },
  'c++': { id: 'cpp', label: 'C++', category: 'code', isBinaryOrMedia: false },
  hpp: { id: 'cpp', label: 'C++ Header', category: 'code', isBinaryOrMedia: false },
  hh: { id: 'cpp', label: 'C++ Header', category: 'code', isBinaryOrMedia: false },
  hxx: { id: 'cpp', label: 'C++ Header', category: 'code', isBinaryOrMedia: false },
  cs: { id: 'csharp', label: 'C#', category: 'code', isBinaryOrMedia: false },
  rb: { id: 'ruby', label: 'Ruby', category: 'code', isBinaryOrMedia: false },
  php: { id: 'php', label: 'PHP', category: 'code', isBinaryOrMedia: false },
  swift: { id: 'swift', label: 'Swift', category: 'code', isBinaryOrMedia: false },
  kt: { id: 'kotlin', label: 'Kotlin', category: 'code', isBinaryOrMedia: false },
  kts: { id: 'kotlin', label: 'Kotlin', category: 'code', isBinaryOrMedia: false },
  scala: { id: 'scala', label: 'Scala', category: 'code', isBinaryOrMedia: false },
  dart: { id: 'dart', label: 'Dart', category: 'code', isBinaryOrMedia: false },
  lua: { id: 'lua', label: 'Lua', category: 'code', isBinaryOrMedia: false },
  r: { id: 'r', label: 'R', category: 'code', isBinaryOrMedia: false },
  jl: { id: 'julia', label: 'Julia', category: 'code', isBinaryOrMedia: false },
  ex: { id: 'elixir', label: 'Elixir', category: 'code', isBinaryOrMedia: false },
  exs: { id: 'elixir', label: 'Elixir', category: 'code', isBinaryOrMedia: false },
  erl: { id: 'erlang', label: 'Erlang', category: 'code', isBinaryOrMedia: false },
  hs: { id: 'haskell', label: 'Haskell', category: 'code', isBinaryOrMedia: false },
  ml: { id: 'ocaml', label: 'OCaml', category: 'code', isBinaryOrMedia: false },
  mli: { id: 'ocaml', label: 'OCaml', category: 'code', isBinaryOrMedia: false },
  clj: { id: 'clojure', label: 'Clojure', category: 'code', isBinaryOrMedia: false },
  cljs: { id: 'clojure', label: 'Clojure', category: 'code', isBinaryOrMedia: false },
  cljc: { id: 'clojure', label: 'Clojure', category: 'code', isBinaryOrMedia: false },
  zig: { id: 'zig', label: 'Zig', category: 'code', isBinaryOrMedia: false },
  nim: { id: 'nim', label: 'Nim', category: 'code', isBinaryOrMedia: false },
  v: { id: 'v', label: 'V', category: 'code', isBinaryOrMedia: false },
  sol: { id: 'solidity', label: 'Solidity', category: 'code', isBinaryOrMedia: false },
  sh: { id: 'shell', label: 'Shell', category: 'code', isBinaryOrMedia: false },
  bash: { id: 'shell', label: 'Bash', category: 'code', isBinaryOrMedia: false },
  zsh: { id: 'shell', label: 'Zsh', category: 'code', isBinaryOrMedia: false },
  fish: { id: 'shell', label: 'Fish', category: 'code', isBinaryOrMedia: false },
  ps1: { id: 'powershell', label: 'PowerShell', category: 'code', isBinaryOrMedia: false },
  bat: { id: 'batch', label: 'Batch', category: 'code', isBinaryOrMedia: false },
  cmd: { id: 'batch', label: 'Batch', category: 'code', isBinaryOrMedia: false },
  sql: { id: 'sql', label: 'SQL', category: 'code', isBinaryOrMedia: false },
  graphql: { id: 'graphql', label: 'GraphQL', category: 'code', isBinaryOrMedia: false },
  gql: { id: 'graphql', label: 'GraphQL', category: 'code', isBinaryOrMedia: false },
  proto: { id: 'protobuf', label: 'Protocol Buffers', category: 'code', isBinaryOrMedia: false },
  wasm: { id: 'wasm', label: 'WebAssembly', category: 'code', isBinaryOrMedia: true },

  // Markup
  htm: { id: 'html', label: 'HTML', category: 'markup', isBinaryOrMedia: false },
  xhtml: { id: 'html', label: 'HTML', category: 'markup', isBinaryOrMedia: false },
  xml: { id: 'xml', label: 'XML', category: 'markup', isBinaryOrMedia: false },
  svg: { id: 'svg', label: 'SVG', category: 'markup', isBinaryOrMedia: false },
  vue: { id: 'vue', label: 'Vue', category: 'markup', isBinaryOrMedia: false },
  svelte: { id: 'svelte', label: 'Svelte', category: 'markup', isBinaryOrMedia: false },
  astro: { id: 'astro', label: 'Astro', category: 'markup', isBinaryOrMedia: false },

  // Stylesheets
  css: { id: 'css', label: 'CSS', category: 'stylesheet', isBinaryOrMedia: false },
  scss: { id: 'scss', label: 'SCSS', category: 'stylesheet', isBinaryOrMedia: false },
  sass: { id: 'sass', label: 'Sass', category: 'stylesheet', isBinaryOrMedia: false },
  less: { id: 'less', label: 'Less', category: 'stylesheet', isBinaryOrMedia: false },
  styl: { id: 'stylus', label: 'Stylus', category: 'stylesheet', isBinaryOrMedia: false },
  pcss: { id: 'postcss', label: 'PostCSS', category: 'stylesheet', isBinaryOrMedia: false },

  // Config
  json: { id: 'json', label: 'JSON', category: 'config', isBinaryOrMedia: false },
  jsonc: { id: 'jsonc', label: 'JSONC', category: 'config', isBinaryOrMedia: false },
  json5: { id: 'json5', label: 'JSON5', category: 'config', isBinaryOrMedia: false },
  yaml: { id: 'yaml', label: 'YAML', category: 'config', isBinaryOrMedia: false },
  yml: { id: 'yaml', label: 'YAML', category: 'config', isBinaryOrMedia: false },
  toml: { id: 'toml', label: 'TOML', category: 'config', isBinaryOrMedia: false },
  ini: { id: 'ini', label: 'INI', category: 'config', isBinaryOrMedia: false },
  cfg: { id: 'config', label: 'Config', category: 'config', isBinaryOrMedia: false },
  conf: { id: 'config', label: 'Config', category: 'config', isBinaryOrMedia: false },
  env: { id: 'dotenv', label: 'Env Config', category: 'config', isBinaryOrMedia: false },
  properties: { id: 'properties', label: 'Properties', category: 'config', isBinaryOrMedia: false },
  lock: { id: 'lockfile', label: 'Lockfile', category: 'config', isBinaryOrMedia: false },
  editorconfig: { id: 'editorconfig', label: 'EditorConfig', category: 'config', isBinaryOrMedia: false },
  gitignore: { id: 'gitignore', label: 'Git Ignore', category: 'config', isBinaryOrMedia: false },
  gitattributes: { id: 'gitattributes', label: 'Git Attributes', category: 'config', isBinaryOrMedia: false },
  dockerignore: { id: 'dockerignore', label: 'Docker Ignore', category: 'config', isBinaryOrMedia: false },
  npmrc: { id: 'npmrc', label: 'npm Config', category: 'config', isBinaryOrMedia: false },

  // Data
  csv: { id: 'csv', label: 'CSV', category: 'data', isBinaryOrMedia: false },
  tsv: { id: 'tsv', label: 'TSV', category: 'data', isBinaryOrMedia: false },
  ndjson: { id: 'ndjson', label: 'JSON Lines', category: 'data', isBinaryOrMedia: false },
  jsonl: { id: 'ndjson', label: 'JSON Lines', category: 'data', isBinaryOrMedia: false },

  // Documentation & Text
  markdown: { id: 'markdown', label: 'Markdown', category: 'documentation', isBinaryOrMedia: false },
  mdx: { id: 'mdx', label: 'MDX', category: 'documentation', isBinaryOrMedia: false },
  rst: { id: 'rst', label: 'reStructuredText', category: 'documentation', isBinaryOrMedia: false },
  adoc: { id: 'asciidoc', label: 'AsciiDoc', category: 'documentation', isBinaryOrMedia: false },
  tex: { id: 'latex', label: 'LaTeX', category: 'documentation', isBinaryOrMedia: false },
  txt: { id: 'text', label: 'Plain Text', category: 'text', isBinaryOrMedia: false },
  rtf: { id: 'rtf', label: 'Rich Text', category: 'text', isBinaryOrMedia: false },
  log: { id: 'log', label: 'Log', category: 'text', isBinaryOrMedia: false },

  // Images
  png: { id: 'png', label: 'PNG Image', category: 'image', isBinaryOrMedia: true },
  gif: { id: 'gif', label: 'GIF Image', category: 'image', isBinaryOrMedia: true },
  webp: { id: 'webp', label: 'WebP Image', category: 'image', isBinaryOrMedia: true },
  bmp: { id: 'bmp', label: 'BMP Image', category: 'image', isBinaryOrMedia: true },
  ico: { id: 'ico', label: 'ICO Icon', category: 'image', isBinaryOrMedia: true },
  avif: { id: 'avif', label: 'AVIF Image', category: 'image', isBinaryOrMedia: true },
  heic: { id: 'heic', label: 'HEIC Image', category: 'image', isBinaryOrMedia: true },

  // Documents
  doc: { id: 'word', label: 'Word Document', category: 'document', isBinaryOrMedia: true },
  docx: { id: 'word', label: 'Word Document', category: 'document', isBinaryOrMedia: true },
  xls: { id: 'excel', label: 'Excel Spreadsheet', category: 'document', isBinaryOrMedia: true },
  xlsx: { id: 'excel', label: 'Excel Spreadsheet', category: 'document', isBinaryOrMedia: true },
  ppt: { id: 'powerpoint', label: 'PowerPoint Presentation', category: 'document', isBinaryOrMedia: true },
  pptx: { id: 'powerpoint', label: 'PowerPoint Presentation', category: 'document', isBinaryOrMedia: true },

  // Media (audio, video, fonts)
  mp3: { id: 'mp3', label: 'MP3 Audio', category: 'media', isBinaryOrMedia: true },
  wav: { id: 'wav', label: 'WAV Audio', category: 'media', isBinaryOrMedia: true },
  ogg: { id: 'ogg', label: 'OGG Audio', category: 'media', isBinaryOrMedia: true },
  flac: { id: 'flac', label: 'FLAC Audio', category: 'media', isBinaryOrMedia: true },
  mp4: { id: 'mp4', label: 'MP4 Video', category: 'media', isBinaryOrMedia: true },
  mov: { id: 'mov', label: 'MOV Video', category: 'media', isBinaryOrMedia: true },
  webm: { id: 'webm', label: 'WebM Video', category: 'media', isBinaryOrMedia: true },
  avi: { id: 'avi', label: 'AVI Video', category: 'media', isBinaryOrMedia: true },
  mkv: { id: 'mkv', label: 'MKV Video', category: 'media', isBinaryOrMedia: true },
  woff: { id: 'woff', label: 'WOFF Font', category: 'media', isBinaryOrMedia: true },
  woff2: { id: 'woff2', label: 'WOFF2 Font', category: 'media', isBinaryOrMedia: true },
  ttf: { id: 'ttf', label: 'TTF Font', category: 'media', isBinaryOrMedia: true },
  otf: { id: 'otf', label: 'OTF Font', category: 'media', isBinaryOrMedia: true },
  eot: { id: 'eot', label: 'EOT Font', category: 'media', isBinaryOrMedia: true },

  // Archives
  zip: { id: 'zip', label: 'ZIP Archive', category: 'archive', isBinaryOrMedia: true },
  tar: { id: 'tar', label: 'TAR Archive', category: 'archive', isBinaryOrMedia: true },
  gz: { id: 'gzip', label: 'Gzip Archive', category: 'archive', isBinaryOrMedia: true },
  tgz: { id: 'tar-gz', label: 'TAR.GZ Archive', category: 'archive', isBinaryOrMedia: true },
  '7z': { id: '7z', label: '7z Archive', category: 'archive', isBinaryOrMedia: true },
  rar: { id: 'rar', label: 'RAR Archive', category: 'archive', isBinaryOrMedia: true },
};

const UNRESOLVED_API_LANGUAGES = new Set([
  '',
  'unknown',
  'other',
  'none',
  'null',
  'undefined',
  'n/a',
  'file',
]);

const TEXT_API_LANGUAGES = new Set(['text', 'plain text', 'plaintext', 'txt']);

const API_LANGUAGE_ALIASES: Record<string, FileTypeSpec> = {
  typescript: EXTENSION_MAP.ts,
  ts: EXTENSION_MAP.ts,
  tsx: EXTENSION_MAP.tsx,
  javascript: EXTENSION_MAP.js,
  js: EXTENSION_MAP.js,
  jsx: EXTENSION_MAP.jsx,
  python: EXTENSION_MAP.py,
  py: EXTENSION_MAP.py,
  rust: EXTENSION_MAP.rs,
  rs: EXTENSION_MAP.rs,
  go: EXTENSION_MAP.go,
  golang: EXTENSION_MAP.go,
  java: EXTENSION_MAP.java,
  c: EXTENSION_MAP.c,
  'c++': EXTENSION_MAP.cpp,
  cpp: EXTENSION_MAP.cpp,
  'c#': EXTENSION_MAP.cs,
  csharp: EXTENSION_MAP.cs,
  ruby: EXTENSION_MAP.rb,
  rb: EXTENSION_MAP.rb,
  php: EXTENSION_MAP.php,
  swift: EXTENSION_MAP.swift,
  kotlin: EXTENSION_MAP.kt,
  scala: EXTENSION_MAP.scala,
  dart: EXTENSION_MAP.dart,
  lua: EXTENSION_MAP.lua,
  r: EXTENSION_MAP.r,
  julia: EXTENSION_MAP.jl,
  elixir: EXTENSION_MAP.ex,
  erlang: EXTENSION_MAP.erl,
  haskell: EXTENSION_MAP.hs,
  ocaml: EXTENSION_MAP.ml,
  clojure: EXTENSION_MAP.clj,
  zig: EXTENSION_MAP.zig,
  nim: EXTENSION_MAP.nim,
  solidity: EXTENSION_MAP.sol,
  shell: EXTENSION_MAP.sh,
  bash: EXTENSION_MAP.bash,
  sh: EXTENSION_MAP.sh,
  zsh: EXTENSION_MAP.zsh,
  fish: EXTENSION_MAP.fish,
  powershell: EXTENSION_MAP.ps1,
  batch: EXTENSION_MAP.bat,
  sql: EXTENSION_MAP.sql,
  graphql: EXTENSION_MAP.graphql,
  protobuf: EXTENSION_MAP.proto,
  'protocol buffers': EXTENSION_MAP.proto,
  markdown: EXTENSION_MAP.md,
  md: EXTENSION_MAP.md,
  mdx: EXTENSION_MAP.mdx,
  html: EXTENSION_MAP.html,
  xml: EXTENSION_MAP.xml,
  svg: EXTENSION_MAP.svg,
  vue: EXTENSION_MAP.vue,
  svelte: EXTENSION_MAP.svelte,
  astro: EXTENSION_MAP.astro,
  css: EXTENSION_MAP.css,
  scss: EXTENSION_MAP.scss,
  sass: EXTENSION_MAP.sass,
  less: EXTENSION_MAP.less,
  json: EXTENSION_MAP.json,
  jsonc: EXTENSION_MAP.jsonc,
  json5: EXTENSION_MAP.json5,
  yaml: EXTENSION_MAP.yaml,
  yml: EXTENSION_MAP.yml,
  toml: EXTENSION_MAP.toml,
  ini: EXTENSION_MAP.ini,
  csv: EXTENSION_MAP.csv,
  tsv: EXTENSION_MAP.tsv,
  dockerfile: BASENAME_MAP.dockerfile,
  makefile: BASENAME_MAP.makefile,
  cmake: BASENAME_MAP['cmakelists.txt'],
  pdf: EXTENSION_MAP.pdf,
  tiff: EXTENSION_MAP.tiff,
  jpeg: EXTENSION_MAP.jpeg,
  png: EXTENSION_MAP.png,
  gif: EXTENSION_MAP.gif,
  webp: EXTENSION_MAP.webp,
};

interface ExtractedFileInfo {
  lowerBase: string;
  extension: string;
}

function extractFileInfo(rawPath: string): ExtractedFileInfo {
  const normalized = (rawPath ?? '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
  const lastSlash = normalized.lastIndexOf('/');
  const basename = lastSlash >= 0 ? normalized.slice(lastSlash + 1) : normalized;
  const lowerBase = basename.toLowerCase();

  if (lowerBase.endsWith('.tar.gz')) {
    return { lowerBase, extension: 'tar.gz' };
  }

  const dotIdx = lowerBase.lastIndexOf('.');
  const extension = dotIdx > 0 && dotIdx < lowerBase.length - 1 ? lowerBase.slice(dotIdx + 1) : '';
  return { lowerBase, extension };
}

function matchPathSpec(info: ExtractedFileInfo): FileTypeSpec | null {
  const { lowerBase, extension } = info;
  if (!lowerBase) return null;

  const exactBasename = BASENAME_MAP[lowerBase];
  if (exactBasename) return exactBasename;

  if (lowerBase.startsWith('.env.')) {
    return BASENAME_MAP['.env'];
  }
  if (lowerBase.startsWith('dockerfile.') || lowerBase.endsWith('.dockerfile')) {
    return BASENAME_MAP.dockerfile;
  }
  if (lowerBase.startsWith('makefile.')) {
    return BASENAME_MAP.makefile;
  }
  if (lowerBase.endsWith('.tar.gz')) {
    return EXTENSION_MAP.tgz;
  }
  if (
    lowerBase.endsWith('.tar.bz2') ||
    lowerBase.endsWith('.tar.xz') ||
    lowerBase.endsWith('.tar.zst')
  ) {
    return { id: 'archive', label: 'Compressed Tarball', category: 'archive', isBinaryOrMedia: true };
  }

  if (extension && EXTENSION_MAP[extension]) {
    return EXTENSION_MAP[extension];
  }

  return null;
}

/**
 * Resolves a file's language/type from its path/filename and optional backend language string.
 * Treats null, undefined, '', 'unknown', 'other', and 'text' (when extension is known) as unresolved,
 * falling back to comprehensive extension + basename (Dockerfile, Makefile, .gitignore, etc.) lookup.
 */
export function resolveFileType(path: string, apiLanguage?: string | null): ResolvedFileType {
  const info = extractFileInfo(path);
  const pathMatch = matchPathSpec(info);

  const trimmedLang = (apiLanguage ?? '').trim();
  const lowerLang = trimmedLang.toLowerCase();
  const isUnresolvedLang = UNRESOLVED_API_LANGUAGES.has(lowerLang);
  const isTextLang = TEXT_API_LANGUAGES.has(lowerLang);
  const isUsableApiLang = !isUnresolvedLang && !isTextLang;

  if (pathMatch) {
    if (isUsableApiLang) {
      const apiAlias = API_LANGUAGE_ALIASES[lowerLang];
      // Disambiguate .h headers when backend explicitly identifies C++
      if (info.extension === 'h' && apiAlias?.id === 'cpp') {
        return { ...EXTENSION_MAP.hpp, extension: info.extension };
      }
      // Allow explicit non-text backend language to enrich plain .txt files
      if (pathMatch.id === 'text' && apiAlias && apiAlias.id !== 'text') {
        return { ...apiAlias, extension: info.extension };
      }
    }
    return { ...pathMatch, extension: info.extension };
  }

  if (isUsableApiLang) {
    const alias = API_LANGUAGE_ALIASES[lowerLang];
    if (alias) {
      return { ...alias, extension: info.extension };
    }
    return {
      id: lowerLang.replace(/\s+/g, '-'),
      label: trimmedLang,
      category: 'code',
      extension: info.extension,
      isBinaryOrMedia: false,
    };
  }

  if (
    /^[a-z0-9]{1,10}$/.test(info.extension) &&
    !UNRESOLVED_API_LANGUAGES.has(info.extension) &&
    !TEXT_API_LANGUAGES.has(info.extension)
  ) {
    return {
      id: info.extension,
      label: info.extension.toUpperCase(),
      category: 'text',
      extension: info.extension,
      isBinaryOrMedia: false,
    };
  }

  return {
    id: 'text',
    label: 'Plain Text',
    category: 'text',
    extension: info.extension,
    isBinaryOrMedia: false,
  };
}

/**
 * Convenience helper returning display label (never returns 'unknown' when path or extension
 * is recognizable; defaults to 'Plain Text' or uppercase extension).
 */
export function getFileLanguageLabel(path: string, apiLanguage?: string | null): string {
  return resolveFileType(path, apiLanguage).label;
}

/**
 * Convenience helper returning normalized language id for syntax highlighting / filtering.
 */
export function getSyntaxLanguage(path: string, apiLanguage?: string | null): string {
  return resolveFileType(path, apiLanguage).id;
}
