/** Start the prototype React interface using its page mount point. */
import { createRoot } from 'react-dom/client'
import { FoundationPreview } from './preview'
import './fonts.css'
import './styles.css'
createRoot(document.getElementById('prototype-preview')!).render(<FoundationPreview />)
