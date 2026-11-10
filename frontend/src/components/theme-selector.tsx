import { Palette, Sun, Moon, Monitor, Check } from 'lucide-react'

/** The shared head script owns preference, persistence and keyboard behavior in both shells. */
export function ThemeSelector() {
  return <div className="lx-theme-picker" data-theme-picker>
    <button type="button" className="lx-theme-trigger" data-theme-trigger title="Change Theme" aria-label="Change Theme" aria-haspopup="menu" aria-expanded="false"><Palette size={18} aria-hidden="true" /></button>
    <div className="lx-theme-menu" data-theme-menu role="menu" aria-label="Theme" hidden>
      {([{ value: 'light', label: 'Light', Icon: Sun }, { value: 'dark', label: 'Dark', Icon: Moon }, { value: 'system', label: 'System', Icon: Monitor }] as const).map(({ value, label, Icon }) =>
        <button key={value} type="button" role="menuitemradio" aria-checked={value === 'system'} tabIndex={-1} data-theme-option={value}><Icon size={16} aria-hidden="true" /><span>{label}</span><span className="lx-theme-check"><Check size={16} aria-hidden="true" /></span></button>)}
    </div>
  </div>
}
