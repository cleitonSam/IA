import StartNode from "./StartNode";
import EndNode from "./EndNode";
import LoopNode from "./LoopNode";
import SendTextNode from "./SendTextNode";
import SendMenuNode from "./SendMenuNode";
import SendImageNode from "./SendImageNode";
import SendAudioNode from "./SendAudioNode";
import SendMediaNode from "./SendMediaNode";
import AIRespondNode from "./AIRespondNode";
import AIClassifyNode from "./AIClassifyNode";
import AISentimentNode from "./AISentimentNode";
import AIQualifyNode from "./AIQualifyNode";
import AIExtractNode from "./AIExtractNode";
import SwitchNode from "./SwitchNode";
import ConditionNode from "./ConditionNode";
import DelayNode from "./DelayNode";
import WaitInputNode from "./WaitInputNode";
import HumanTransferNode from "./HumanTransferNode";
import WebhookNode from "./WebhookNode";
import AIMenuNode from "./AIMenuNode";
import SetVariableNode from "./SetVariableNode";
import GetVariableNode from "./GetVariableNode";
import GenerateProtocolNode from "./GenerateProtocolNode";
import SearchNode from "./SearchNode";
import RedisNode from "./RedisNode";
import SourceFilterNode from "./SourceFilterNode";
import MenuFixoIANode from "./MenuFixoIANode";
import AIMenuDinamicoIANode from "./AIMenuDinamicoIANode";
import BusinessHoursNode from "./BusinessHoursNode";
import GoToMenuNode from "./GoToMenuNode";

export const nodeTypes = {
  start:         StartNode,
  end:           EndNode,
  loop:          LoopNode,
  sendText:      SendTextNode,
  sendMenu:      SendMenuNode,
  sendImage:     SendImageNode,
  sendAudio:     SendAudioNode,
  sendMedia:     SendMediaNode,
  aiRespond:     AIRespondNode,
  aiClassify:    AIClassifyNode,
  aiSentiment:   AISentimentNode,
  aiQualify:     AIQualifyNode,
  aiExtract:     AIExtractNode,
  switch:        SwitchNode,
  condition:     ConditionNode,
  delay:         DelayNode,
  waitInput:     WaitInputNode,
  humanTransfer: HumanTransferNode,
  webhook:       WebhookNode,
  aiMenu:        AIMenuNode,
  setVariable:   SetVariableNode,
  getVariable:   GetVariableNode,
  generateProtocol: GenerateProtocolNode,
  search:           SearchNode,
  redis:            RedisNode,
  sourceFilter:     SourceFilterNode,
  menuFixoIA:       MenuFixoIANode,
  aiMenuDinamicoIA: AIMenuDinamicoIANode,
  businessHours:    BusinessHoursNode,
  goToMenu:         GoToMenuNode,
};
