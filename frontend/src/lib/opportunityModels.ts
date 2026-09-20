import type { DiscoveryObjective, OpportunityModelId } from './types'

export const OPPORTUNITY_MODEL_LABELS: Record<OpportunityModelId, string> = {
  'web_conversion.no_verified_web_presence': 'Official website',
  'web_conversion.mobile_performance': 'Mobile performance',
  'web_conversion.booking_contact_path': 'Booking/contact path',
  'web_conversion.restaurant_reservation_path': 'Restaurant reservation path',
  'web_conversion.restaurant_customer_path': 'Restaurant customer path',
  'web_conversion.fitness_membership_path': 'Fitness membership path',
  'web_conversion.retail_product_path': 'Retail product path',
  'web_conversion.clinic_patient_path': 'Clinic patient path',
  'social_presence.dormant_official_presence': 'Social activity',
}

export interface OpportunityModelScope {
  modelIds: OpportunityModelId[]
  error: string | null
}

export function opportunityModelScopeForText(
  offering: string,
  goal: string,
  targetSectors: string[] = [],
  additionalSignals: string[] = [],
): OpportunityModelScope {
  const text = [offering, goal, ...additionalSignals].join(' ').toLowerCase()
  const industry = targetSectors.join(' ').toLowerCase()
  const hasWebIntent = /website|web design|web development|landing page|conversion|cms|wordpress|seo|booking|contact path/.test(text)
  const hasSocialIntent = /social|instagram|facebook|tiktok|content|reels|short.form|short form/.test(text)
  if (hasWebIntent && hasSocialIntent) {
    return {
      modelIds: [],
      error: 'Choose one primary service family: Web & Conversion or Social Presence & Content.',
    }
  }
  if (!hasWebIntent && !hasSocialIntent) {
    return {
      modelIds: [],
      error: 'OpportunityCue currently supports Web & Conversion and Social Presence & Content. Make the offering more specific.',
    }
  }
  if (hasSocialIntent) {
    return { modelIds: ['social_presence.dormant_official_presence'], error: null }
  }

  const models: OpportunityModelId[] = []
  const redesignOnly =
    /redesign|rebuild|revamp|overhaul|website refresh/.test(text) &&
    !/new website|website development|build a website|create a website|landing page|no website/.test(text)
  if (!redesignOnly) models.push('web_conversion.no_verified_web_presence')
  models.push('web_conversion.mobile_performance')
  if (/restaurant|cafe/.test(industry)) {
    models.push('web_conversion.restaurant_customer_path')
  } else if (/fitness|gym/.test(industry)) {
    models.push('web_conversion.fitness_membership_path')
  } else if (/boutique|retail|fashion/.test(industry)) {
    models.push('web_conversion.retail_product_path')
  } else if (/dental|dentist|clinic/.test(industry)) {
    models.push('web_conversion.clinic_patient_path')
  } else if (/booking|appointment|inquiry|contact path/.test(text)) {
    models.push('web_conversion.booking_contact_path')
  }
  return { modelIds: [...new Set(models)], error: null }
}

export function opportunityModelScopeForObjective(
  objective: DiscoveryObjective,
): OpportunityModelScope {
  return opportunityModelScopeForText(
    objective.offering ?? '',
    '',
    objective.target_sectors,
    [...objective.triggers, ...objective.signals_to_look_for],
  )
}
