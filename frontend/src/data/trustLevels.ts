// Per-Community trust levels (decisions D62 to D77). The server owns every rule; this file
// only names the shapes it returns and turns requirements into short sentences.

export type TrustLevel = 'New' | 'Member' | 'Trusted'

export const TRUST_LEVELS: TrustLevel[] = ['New', 'Member', 'Trusted']

export type TrustRequirements = {
  member: { needs: number; have: number; met: boolean }
  trusted: {
    contributions: { needs: number; have: number; met: boolean }
    days: { needs: number; have: number; met: boolean }
    clean: { needs: number; met: boolean }
  }
}

export type MemberLevel = {
  user: string
  full_name?: string
  level: TrustLevel
  locked: number
  accepted: number
  level_changed_at?: string | null
  pending?: number
  requirements: TrustRequirements
}

export type MyLevel = MemberLevel & { community: string; title: string }

export type TrustSettings = {
  enabled: number
  member_count: number
  trusted_count: number
  trusted_days: number
  clean_days: number
}

export const levelDescriptions: Record<TrustLevel, string> = {
  New: 'Posts wait for approval when the Community requires it.',
  Member: 'Posts publish without approval.',
  Trusted: 'Posts publish without approval and skip the link, image, file and mention caps.',
}

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** One line per requirement for the next level, each marked met or not. */
export function nextSteps(level: TrustLevel, requirements: TrustRequirements) {
  if (level === 'New') {
    const { needs, have, met } = requirements.member
    return [
      {
        label: `${plural(have, 'accepted contribution')} of ${needs} for Member`,
        met,
      },
    ]
  }
  if (level === 'Member') {
    const { contributions, days, clean } = requirements.trusted
    return [
      {
        label: `${plural(contributions.have, 'accepted contribution')} of ${contributions.needs}`,
        met: contributions.met,
      },
      { label: `${plural(days.have, 'day')} as a member of ${days.needs}`, met: days.met },
      {
        label: clean.met
          ? `No posts removed, reports upheld or bans in the last ${plural(clean.needs, 'day')}`
          : `A post was removed, a report upheld or a ban applied in the last ${plural(clean.needs, 'day')}`,
        met: clean.met,
      },
    ]
  }
  return []
}

export function summary(member: MemberLevel) {
  if (member.pending) return 'Not worked out yet'
  return plural(member.accepted, 'accepted contribution')
}
