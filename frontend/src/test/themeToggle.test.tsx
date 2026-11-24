import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ThemeToggle } from '../components/shared/ThemeToggle';
import { useAppStore } from '../stores/useAppStore';

describe('Theme switching (light / dark mode)', () => {
  beforeEach(() => {
    useAppStore.getState().setTheme('dark');
  });

  it('toggles between dark and light mode and updates document.documentElement.classList', () => {
    expect(document.documentElement.classList.contains('dark')).toBe(true);

    render(<ThemeToggle showLabel />);

    const toLightBtn = screen.getByRole('button', { name: /Switch to light mode/i });
    expect(toLightBtn).toBeInTheDocument();

    fireEvent.click(toLightBtn);

    expect(useAppStore.getState().resolvedTheme).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(screen.getByRole('button', { name: /Switch to dark mode/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Switch to dark mode/i }));

    expect(useAppStore.getState().resolvedTheme).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});
