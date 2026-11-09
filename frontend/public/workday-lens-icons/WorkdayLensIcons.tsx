import * as React from "react";

type IconProps = React.SVGProps<SVGSVGElement> & {
  size?: number;
};

export function WorkdayLensLogo({ size = 32, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 256 256" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <defs>
        <linearGradient id="wl-sky" x1="40" y1="20" x2="218" y2="236" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFD166" />
          <stop offset="0.42" stopColor="#F97316" />
          <stop offset="1" stopColor="#2A102B" />
        </linearGradient>
        <linearGradient id="wl-dune1" x1="27" y1="123" x2="230" y2="178" gradientUnits="userSpaceOnUse">
          <stop stopColor="#D86A1E" />
          <stop offset="1" stopColor="#6F1D2B" />
        </linearGradient>
        <linearGradient id="wl-dune2" x1="18" y1="158" x2="236" y2="202" gradientUnits="userSpaceOnUse">
          <stop stopColor="#A8441E" />
          <stop offset="0.55" stopColor="#7A2330" />
          <stop offset="1" stopColor="#250B28" />
        </linearGradient>
        <linearGradient id="wl-dune3" x1="26" y1="192" x2="226" y2="224" gradientUnits="userSpaceOnUse">
          <stop stopColor="#57203A" />
          <stop offset="1" stopColor="#16081F" />
        </linearGradient>
      </defs>
      <circle cx="128" cy="128" r="118" fill="url(#wl-sky)" />
      <path d="M13 130C50 107 68 104 99 124C124 141 142 141 167 126C192 111 213 111 244 130V244H13V130Z" fill="url(#wl-dune1)" />
      <path d="M0 165C35 151 68 149 101 162C139 178 165 183 201 169C225 160 241 158 256 162V256H0V165Z" fill="url(#wl-dune2)" />
      <path d="M0 211C42 191 75 185 113 199C153 214 188 212 256 187V256H0V211Z" fill="url(#wl-dune3)" />
    </svg>
  );
}

export function FocusTimeIcon({ size = 64, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <circle cx="64" cy="64" r="58" fill="#FFF6EC" stroke="#F7DCC4" strokeWidth="2" />
      <circle cx="64" cy="64" r="29" stroke="#F97316" strokeWidth="8" />
      <circle cx="64" cy="64" r="10" fill="#F97316" />
    </svg>
  );
}

export function MeetingsTimeIcon({ size = 64, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <circle cx="64" cy="64" r="58" fill="#FFF6EC" stroke="#F7DCC4" strokeWidth="2" />
      <path d="M45 57C51.6274 57 57 51.6274 57 45C57 38.3726 51.6274 33 45 33C38.3726 33 33 38.3726 33 45C33 51.6274 38.3726 57 45 57Z" stroke="#D97757" strokeWidth="7" strokeLinecap="round" />
      <path d="M27 88C29.5 73.5 37.5 67 49 67C60.5 67 68.5 73.5 71 88" stroke="#D97757" strokeWidth="7" strokeLinecap="round" />
      <path d="M74 54C80 54 84.5 49.5 84.5 43.5C84.5 37.5 80 33 74 33" stroke="#D97757" strokeWidth="7" strokeLinecap="round" />
      <path d="M80 67C90 69 96 76 98 88" stroke="#D97757" strokeWidth="7" strokeLinecap="round" />
    </svg>
  );
}

export function CommsTimeIcon({ size = 64, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <circle cx="64" cy="64" r="58" fill="#FFF8E8" stroke="#F6E3BA" strokeWidth="2" />
      <path d="M36 84L47 80C39.5 74.7 35 67.5 35 59.5C35 43.8 48.2 32 66 32C83.8 32 97 43.8 97 59.5C97 75.2 83.8 87 66 87C58 87 51.5 85.4 47 80L36 84Z" stroke="#E5A111" strokeWidth="7" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function DeepWorkIcon({ size = 24, color = "#F97316", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <circle cx="32" cy="32" r="21" stroke={color} strokeWidth="5" />
      <circle cx="32" cy="32" r="7" fill={color} />
    </svg>
  );
}

export function MeetingsIcon({ size = 24, color = "#D97757", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M23 28C28 28 32 24 32 19C32 14 28 10 23 10C18 10 14 14 14 19C14 24 18 28 23 28Z" stroke={color} strokeWidth="5" strokeLinecap="round" />
      <path d="M10 48C12 38 17 33 25 33C33 33 38 38 40 48" stroke={color} strokeWidth="5" strokeLinecap="round" />
      <path d="M42 26C46.5 26 50 22.5 50 18C50 13.5 46.5 10 42 10" stroke={color} strokeWidth="5" strokeLinecap="round" />
      <path d="M45 33C52 35 56 40 57 48" stroke={color} strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function CommsIcon({ size = 24, color = "#E5A111", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M15 45L23 42C18 38.5 15 33.5 15 28C15 17.5 24 10 36 10C48 10 57 17.5 57 28C57 38.5 48 46 36 46C30.5 46 26 44.8 23 42L15 45Z" stroke={color} strokeWidth="5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function BreaksIcon({ size = 24, color = "#68A899", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M18 25H42V38C42 45 37 50 30 50C23 50 18 45 18 38V25Z" stroke={color} strokeWidth="5" strokeLinejoin="round" />
      <path d="M42 30H48C53 30 56 33 56 38C56 43 53 46 48 46H42" stroke={color} strokeWidth="5" strokeLinecap="round" />
      <path d="M25 12V20M36 12V20M18 55H43" stroke={color} strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}

export function StarburstIcon({ size = 24, color = "#F97316", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M32 6C35.2 22.4 41.6 28.8 58 32C41.6 35.2 35.2 41.6 32 58C28.8 41.6 22.4 35.2 6 32C22.4 28.8 28.8 22.4 32 6Z" fill={color} />
    </svg>
  );
}

export function InsightBulbIcon({ size = 24, color = "#E5A111", ...props }: IconProps & { color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <path d="M32 8C22 8 15 15.5 15 25C15 31 18 36 23 39.5V45H41V39.5C46 36 49 31 49 25C49 15.5 42 8 32 8Z" stroke={color} strokeWidth="4.5" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M25 52H39M28 58H36" stroke={color} strokeWidth="4.5" strokeLinecap="round" />
    </svg>
  );
}

export function FolderBadgeIcon({ size = 48, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <rect x="13" y="13" width="102" height="102" rx="26" fill="#FFF6EC" stroke="#F5E6D5" strokeWidth="2" />
      <path d="M35 82V45C35 41.7 37.7 39 41 39H56L63 47H87C90.3 47 93 49.7 93 53V82C93 85.3 90.3 88 87 88H41C37.7 88 35 85.3 35 82Z" stroke="#E46F1A" strokeWidth="7" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

export function MusicBadgeIcon({ size = 48, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <rect x="13" y="13" width="102" height="102" rx="26" fill="#FFF6EC" stroke="#F5E6D5" strokeWidth="2" />
      <path d="M57 77V35L88 29V72" stroke="#E46F1A" strokeWidth="7" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M44 90C51.18 90 57 85.52 57 80C57 74.48 51.18 70 44 70C36.82 70 31 74.48 31 80C31 85.52 36.82 90 44 90Z" fill="#E46F1A" />
      <path d="M75 85C82.18 85 88 80.52 88 75C88 69.48 82.18 65 75 65C67.82 65 62 69.48 62 75C62 80.52 67.82 85 75 85Z" fill="#E46F1A" />
      <path d="M57 47L88 41" stroke="#E46F1A" strokeWidth="7" strokeLinecap="round" />
    </svg>
  );
}

export function SunriseBadgeIcon({ size = 48, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 128 128" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <rect x="13" y="13" width="102" height="102" rx="26" fill="#FFF6EC" stroke="#F5E6D5" strokeWidth="2" />
      <path d="M39 76C40.6 64.5 50.2 56 64 56C77.8 56 87.4 64.5 89 76" stroke="#E46F1A" strokeWidth="7" strokeLinecap="round" />
      <path d="M34 89H94M64 35V45M44 42L50 50M84 42L78 50M28 65H39M89 65H100" stroke="#E46F1A" strokeWidth="7" strokeLinecap="round" />
    </svg>
  );
}
