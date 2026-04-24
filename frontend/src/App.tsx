import DevPage from "./pages/dev";
import HomePage from "./pages/home";
import { Route, Routes } from "react-router-dom";

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/dev" element={<DevPage />} />
    </Routes>
  );
}

export default App;
