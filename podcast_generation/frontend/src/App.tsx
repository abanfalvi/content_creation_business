import HomePage from './pages/HomePage'
import NotebookPage from './pages/NotebookPage'
import { useRoute } from './router'

export default function App() {
  const route = useRoute()
  // `key` gives each notebook its own page state (selection, open chat), instead of carrying it over from the last one.
  return route.page === 'notebook' ? <NotebookPage key={route.id} id={route.id} /> : <HomePage />
}
