import academia from "./academia.json";
import clinica from "./clinica.json";
import imobiliaria from "./imobiliaria.json";
import ecommerce from "./ecommerce.json";

export type TemplateFluxo = {
  nome: string;
  descricao: string;
  ativo: boolean;
  nodes: any[];
  edges: any[];
};

export const TEMPLATES_FLUXO: TemplateFluxo[] = [
  academia as TemplateFluxo,
  clinica as TemplateFluxo,
  imobiliaria as TemplateFluxo,
  ecommerce as TemplateFluxo,
];
