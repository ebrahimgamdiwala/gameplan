// The router waits for the signed-in user's record before it picks a page, so a Guest is
// never mistaken for a member who joined nothing. Someone without a Gameplan role, like a
// site's Administrator, is never in that record. The router must stop waiting once the
// reply lands, not sit out its 5 second timeout on every navigation.
// guest-access.cy.ts covers the Guest side: `/g` takes them into their Community.
import { resetData } from '../../support/seed'

const EMAIL = 'no-gameplan-role@example.com'
const PASSWORD = 'No-gameplan-role-1'

describe('A signed-in account without a Gameplan role', () => {
  beforeEach(() => {
    resetData('onboarded')
    cy.request('POST', '/api/method/frappe.client.insert', {
      doc: {
        doctype: 'User',
        email: EMAIL,
        first_name: 'Desk',
        send_welcome_email: 0,
        new_password: PASSWORD,
        roles: [{ role: 'System Manager' }],
      },
    })
    cy.login(EMAIL, PASSWORD)
  })

  it('routes without waiting for a record that never comes', () => {
    cy.visit('/g')
    // The old wait took 5 seconds per guard, and a reload ran two of them.
    cy.location('pathname', { timeout: 2000 }).should('not.match', /^\/g\/?$/)

    cy.window().then((win) => {
      const app = (win.document.querySelector('#app') as any).__vue_app__
      app.config.globalProperties.$router.push('/notifications')
    })
    cy.location('pathname', { timeout: 2000 }).should('eq', '/g/notifications')
  })
})
