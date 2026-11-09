import { resetData } from '../../support/seed'

function row(name: string) {
  return cy
    .get('[data-testid="trust-level-list"] [data-testid="moderation-row"]')
    .filter(`:contains("${name}")`)
}

function confirm(reason: string, button: string) {
  cy.get('[role="dialog"] textarea').type(reason)
  cy.get('[role="dialog"]').contains('button', button).click()
}

describe('Trust levels', () => {
  it('turns levels on, lets a moderator change and lock a level, and shows the member their level', () => {
    resetData('space_with_discussion').then((ids) => {
      cy.request('POST', '/api/method/gameplan.approval_policy.set_policy', {
        community: ids.community,
        count: 3,
      })
      cy.visit(`/g/community/${ids.community}/moderation?tab=levels`)
      cy.contains('Trust levels are off').should('be.visible')

      cy.visit(`/g/community/${ids.community}/moderation`)
      cy.contains('button', 'Approval settings').click()
      cy.contains('label', 'Use trust levels').click()
      cy.get('[role="dialog"]').contains('Trusted needs').should('be.visible')
      cy.contains('button', 'Save approval policy').click()
      cy.contains('Approval policy saved.').should('be.visible')

      cy.visit(`/g/community/${ids.community}/moderation?tab=levels`)
      cy.contains('header:visible', 'Trust levels').should('be.visible')
      row('Second Member').should('contain.text', 'New')

      row('Second Member').find('button[aria-label="More actions"]').click()
      cy.contains('[role="menuitem"]', 'Show requirements').click()
      // No job worker runs here, so the member is still waiting for the background job.
      cy.get('[data-testid="trust-requirements"]').should(
        'contain.text',
        'not reached this member yet',
      )

      row('Second Member')
        .contains('button', /^\s*Change\s*$/)
        .click()
      cy.get('[role="dialog"]').contains('button', 'New').click()
      cy.contains('[role="option"]', /^Trusted$/).click()
      confirm('Long-time contributor', 'Change level')
      cy.contains('Level changed to Trusted.').should('be.visible')
      row('Second Member').should('contain.text', 'Trusted')

      row('Second Member').find('button[aria-label="More actions"]').click()
      cy.contains('[role="menuitem"]', 'Lock level').click()
      confirm('Keep while we review', 'Lock')
      row('Second Member').should('contain.text', 'Locked')

      cy.contains('[role="radio"]', 'Trusted').click()
      cy.get('[data-testid="trust-level-list"] [data-testid="moderation-row"]').should(
        'have.length',
        1,
      )

      cy.visit(`/g/community/${ids.community}/moderation?tab=history`)
      cy.get('[data-testid="history-row"]').first().should('contain.text', 'Level Locked')
      cy.contains('[data-testid="history-row"]', 'Level Changed')
        .should('contain.text', 'New → Trusted')
        .and('contain.text', 'Long-time contributor')

      cy.switchUser('secondMember')
      cy.visit('/g/submissions')
      cy.get('[data-testid="my-trust-levels"]')
        .should('contain.text', 'Acme')
        .and('contain.text', 'Trusted')
      cy.visit('/g/notifications')
      cy.contains('You are now a Trusted in Acme.').should('be.visible')

      cy.switchUser('member')
      cy.request({
        method: 'POST',
        url: '/api/method/gameplan.trust_levels.member_levels',
        body: { community: ids.community },
        failOnStatusCode: false,
      })
        .its('status')
        .should('eq', 403)
    })
  })
})
