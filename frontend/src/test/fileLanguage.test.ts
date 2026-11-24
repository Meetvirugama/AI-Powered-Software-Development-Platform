import { describe, it, expect } from 'vitest';
import {
  resolveFileType,
  getFileLanguageLabel,
  getSyntaxLanguage,
  type FileCategory,
} from '../lib/fileLanguage';

describe('fileLanguage resolver (R2)', () => {
  describe('explicitly mandated R2 extensions', () => {
    it.each([
      { path: 'README.md', id: 'markdown', label: 'Markdown', category: 'documentation', ext: 'md', binary: false },
      { path: 'public/index.html', id: 'html', label: 'HTML', category: 'markup', ext: 'html', binary: false },
      { path: 'assets/scan.tiff', id: 'tiff', label: 'TIFF Image', category: 'image', ext: 'tiff', binary: true },
      { path: 'assets/scan.tif', id: 'tiff', label: 'TIFF Image', category: 'image', ext: 'tif', binary: true },
      { path: 'images/photo.jpeg', id: 'jpeg', label: 'JPEG Image', category: 'image', ext: 'jpeg', binary: true },
      { path: 'images/photo.jpg', id: 'jpeg', label: 'JPEG Image', category: 'image', ext: 'jpg', binary: true },
      { path: 'docs/spec.pdf', id: 'pdf', label: 'PDF Document', category: 'document', ext: 'pdf', binary: true },
      { path: 'src/main.rs', id: 'rust', label: 'Rust', category: 'code', ext: 'rs', binary: false },
    ] as const)(
      'resolves $path even when apiLanguage is "unknown" or null',
      ({ path, id, label, category, ext, binary }) => {
        for (const apiLang of ['unknown', null, undefined, '', 'text']) {
          const resolved = resolveFileType(path, apiLang);
          expect(resolved.id).toBe(id);
          expect(resolved.label).toBe(label);
          expect(resolved.category).toBe(category);
          expect(resolved.extension).toBe(ext);
          expect(resolved.isBinaryOrMedia).toBe(binary);
          expect(getFileLanguageLabel(path, apiLang)).toBe(label);
          expect(getFileLanguageLabel(path, apiLang).toLowerCase()).not.toBe('unknown');
          expect(getSyntaxLanguage(path, apiLang)).toBe(id);
        }
      },
    );
  });

  describe('case-insensitivity across extensions and basenames', () => {
    it.each([
      ['docs/GUIDE.MD', 'Markdown', 'markdown'],
      ['WEB/INDEX.HTML', 'HTML', 'html'],
      ['SCANS/PAGE.TIFF', 'TIFF Image', 'tiff'],
      ['PHOTOS/AVATAR.JPEG', 'JPEG Image', 'jpeg'],
      ['MANUALS/SPEC.PDF', 'PDF Document', 'pdf'],
      ['CRATE/LIB.RS', 'Rust', 'rust'],
      ['DOCKERFILE', 'Dockerfile', 'dockerfile'],
      ['MAKEFILE', 'Makefile', 'makefile'],
      ['CMAKELISTS.TXT', 'CMake', 'cmake'],
    ])('resolves %s to %s (%s)', (path, expectedLabel, expectedId) => {
      expect(getFileLanguageLabel(path, 'unknown')).toBe(expectedLabel);
      expect(getSyntaxLanguage(path, null)).toBe(expectedId);
    });
  });

  describe('comprehensive category coverage', () => {
    const cases: Array<[string, FileCategory, boolean]> = [
      // Programming (code)
      ['a.ts', 'code', false],
      ['a.tsx', 'code', false],
      ['a.js', 'code', false],
      ['a.jsx', 'code', false],
      ['a.mjs', 'code', false],
      ['a.cjs', 'code', false],
      ['a.py', 'code', false],
      ['a.pyw', 'code', false],
      ['a.go', 'code', false],
      ['a.java', 'code', false],
      ['a.c', 'code', false],
      ['a.h', 'code', false],
      ['a.cpp', 'code', false],
      ['a.cc', 'code', false],
      ['a.cxx', 'code', false],
      ['a.hpp', 'code', false],
      ['a.cs', 'code', false],
      ['a.rb', 'code', false],
      ['a.php', 'code', false],
      ['a.swift', 'code', false],
      ['a.kt', 'code', false],
      ['a.kts', 'code', false],
      ['a.scala', 'code', false],
      ['a.dart', 'code', false],
      ['a.lua', 'code', false],
      ['a.r', 'code', false],
      ['a.jl', 'code', false],
      ['a.ex', 'code', false],
      ['a.exs', 'code', false],
      ['a.erl', 'code', false],
      ['a.hs', 'code', false],
      ['a.ml', 'code', false],
      ['a.clj', 'code', false],
      ['a.zig', 'code', false],
      ['a.nim', 'code', false],
      ['a.v', 'code', false],
      ['a.sol', 'code', false],
      ['a.sh', 'code', false],
      ['a.bash', 'code', false],
      ['a.zsh', 'code', false],
      ['a.fish', 'code', false],
      ['a.ps1', 'code', false],
      ['a.bat', 'code', false],
      ['a.cmd', 'code', false],
      ['a.sql', 'code', false],
      ['a.graphql', 'code', false],
      ['a.gql', 'code', false],
      ['a.proto', 'code', false],
      ['a.wasm', 'code', true],

      // Markup
      ['a.htm', 'markup', false],
      ['a.xhtml', 'markup', false],
      ['a.xml', 'markup', false],
      ['a.svg', 'markup', false],
      ['a.vue', 'markup', false],
      ['a.svelte', 'markup', false],
      ['a.astro', 'markup', false],

      // Stylesheets
      ['a.css', 'stylesheet', false],
      ['a.scss', 'stylesheet', false],
      ['a.sass', 'stylesheet', false],
      ['a.less', 'stylesheet', false],
      ['a.styl', 'stylesheet', false],
      ['a.pcss', 'stylesheet', false],

      // Config
      ['a.json', 'config', false],
      ['a.jsonc', 'config', false],
      ['a.json5', 'config', false],
      ['a.yaml', 'config', false],
      ['a.yml', 'config', false],
      ['a.toml', 'config', false],
      ['a.ini', 'config', false],
      ['a.cfg', 'config', false],
      ['a.conf', 'config', false],
      ['a.env', 'config', false],
      ['a.properties', 'config', false],
      ['a.lock', 'config', false],
      ['a.editorconfig', 'config', false],
      ['a.gitignore', 'config', false],
      ['a.gitattributes', 'config', false],
      ['a.dockerignore', 'config', false],
      ['a.npmrc', 'config', false],

      // Data
      ['a.csv', 'data', false],
      ['a.tsv', 'data', false],
      ['a.ndjson', 'data', false],
      ['a.jsonl', 'data', false],

      // Documentation & Text
      ['a.markdown', 'documentation', false],
      ['a.mdx', 'documentation', false],
      ['a.rst', 'documentation', false],
      ['a.adoc', 'documentation', false],
      ['a.tex', 'documentation', false],
      ['a.txt', 'text', false],
      ['a.rtf', 'text', false],
      ['a.log', 'text', false],

      // Images
      ['a.png', 'image', true],
      ['a.gif', 'image', true],
      ['a.webp', 'image', true],
      ['a.bmp', 'image', true],
      ['a.ico', 'image', true],
      ['a.avif', 'image', true],
      ['a.heic', 'image', true],

      // Documents
      ['a.doc', 'document', true],
      ['a.docx', 'document', true],
      ['a.xls', 'document', true],
      ['a.xlsx', 'document', true],
      ['a.ppt', 'document', true],
      ['a.pptx', 'document', true],

      // Media (audio, video, fonts)
      ['a.mp3', 'media', true],
      ['a.wav', 'media', true],
      ['a.ogg', 'media', true],
      ['a.flac', 'media', true],
      ['a.mp4', 'media', true],
      ['a.mov', 'media', true],
      ['a.webm', 'media', true],
      ['a.avi', 'media', true],
      ['a.mkv', 'media', true],
      ['a.woff', 'media', true],
      ['a.woff2', 'media', true],
      ['a.ttf', 'media', true],
      ['a.otf', 'media', true],
      ['a.eot', 'media', true],

      // Archives
      ['a.zip', 'archive', true],
      ['a.tar', 'archive', true],
      ['a.gz', 'archive', true],
      ['a.tgz', 'archive', true],
      ['a.7z', 'archive', true],
      ['a.rar', 'archive', true],
    ];

    it.each(cases)('categorizes %s as %s (binary=%s)', (path, expectedCategory, expectedBinary) => {
      const resolved = resolveFileType(path, 'unknown');
      expect(resolved.category).toBe(expectedCategory);
      expect(resolved.isBinaryOrMedia).toBe(expectedBinary);
      expect(resolved.label).not.toBe('unknown');
      expect(resolved.label.length).toBeGreaterThan(0);
    });
  });

  describe('extensionless basenames & dotfiles', () => {
    it.each([
      ['Dockerfile', 'Dockerfile', 'config'],
      ['infra/Dockerfile', 'Dockerfile', 'config'],
      ['Dockerfile.prod', 'Dockerfile', 'config'],
      ['Makefile', 'Makefile', 'config'],
      ['GNUmakefile', 'Makefile', 'config'],
      ['CMakeLists.txt', 'CMake', 'config'],
      ['Procfile', 'Procfile', 'config'],
      ['.gitignore', 'Git Ignore', 'config'],
      ['.gitattributes', 'Git Attributes', 'config'],
      ['.dockerignore', 'Docker Ignore', 'config'],
      ['.npmrc', 'npm Config', 'config'],
      ['.editorconfig', 'EditorConfig', 'config'],
      ['.env', 'Env Config', 'config'],
      ['.env.local', 'Env Config', 'config'],
      ['.env.production', 'Env Config', 'config'],
    ])('resolves %s -> %s (%s)', (path, expectedLabel, expectedCategory) => {
      const resolved = resolveFileType(path, 'unknown');
      expect(resolved.label).toBe(expectedLabel);
      expect(resolved.category).toBe(expectedCategory);
    });
  });

  describe('multi-dot filenames and cross-platform paths', () => {
    it('handles multi-dot extensions and Windows backslashes', () => {
      expect(resolveFileType('src/utils/foo.test.ts')).toMatchObject({
        id: 'typescript',
        label: 'TypeScript',
        extension: 'ts',
      });
      expect(resolveFileType('src/types/config.d.ts')).toMatchObject({
        id: 'typescript',
        label: 'TypeScript',
        extension: 'ts',
      });
      expect(resolveFileType('dist/release.tar.gz')).toMatchObject({
        id: 'tar-gz',
        label: 'TAR.GZ Archive',
        category: 'archive',
        extension: 'tar.gz',
        isBinaryOrMedia: true,
      });
      expect(resolveFileType('C:\\Users\\dev\\project\\main.rs', 'unknown')).toMatchObject({
        id: 'rust',
        label: 'Rust',
        category: 'code',
        extension: 'rs',
      });
    });
  });

  describe('apiLanguage normalization & fallbacks', () => {
    it('uses valid apiLanguage for extensionless files and disambiguation', () => {
      expect(resolveFileType('bin/run', 'Python')).toMatchObject({
        id: 'python',
        label: 'Python',
        category: 'code',
      });
      expect(resolveFileType('include/widget.h', 'C++')).toMatchObject({
        id: 'cpp',
        label: 'C++ Header',
        extension: 'h',
      });
      expect(resolveFileType('notes.txt', 'Markdown')).toMatchObject({
        id: 'markdown',
        label: 'Markdown',
        extension: 'txt',
      });
    });

    it('never returns "unknown" for unrecognized extensions or empty paths', () => {
      expect(resolveFileType('blob.xyz', 'unknown')).toMatchObject({
        id: 'xyz',
        label: 'XYZ',
        extension: 'xyz',
      });
      expect(resolveFileType('foo.unknown', 'unknown')).toMatchObject({
        id: 'text',
        label: 'Plain Text',
        category: 'text',
        extension: 'unknown',
      });
      expect(getFileLanguageLabel('foo.unknown', 'unknown').toLowerCase()).not.toBe('unknown');
      expect(resolveFileType('bar.other', null)).toMatchObject({
        id: 'text',
        label: 'Plain Text',
        category: 'text',
        extension: 'other',
      });
      expect(resolveFileType('LICENSE', null)).toMatchObject({
        id: 'text',
        label: 'Plain Text',
        extension: '',
      });
      expect(resolveFileType('', undefined)).toMatchObject({
        id: 'text',
        label: 'Plain Text',
        extension: '',
      });
    });
  });
});
