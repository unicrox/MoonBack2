import DevPage from "./pages/dev";
import HomePage from "./pages/home";
import InvestigatePage from "./pages/investigate";
import { Route, Routes } from "react-router-dom";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/dev" element={<DevPage />} />
      <Route path="/investigate" element={<InvestigatePage />} />
    </Routes>
  );
}

export default App;
