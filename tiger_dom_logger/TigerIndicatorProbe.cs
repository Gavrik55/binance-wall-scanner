//------------------------------------------------------------------------------
//
// Tiny diagnostic custom indicator for Tiger.com Windows.
// If this indicator does not appear in Tiger, Tiger is not loading custom .cs files.
//
//------------------------------------------------------------------------------

using System.ComponentModel;
using System.Runtime.Serialization;
using TigerTrade.Chart.Base;
using TigerTrade.Chart.Indicators.Common;
using TigerTrade.Chart.Indicators.Enums;
using TigerTrade.Dx;

namespace TigerTrade.Chart.Indicators.Custom
{
    [DataContract(Name = "TigerIndicatorProbe", Namespace = "http://schemas.datacontract.org/2004/07/TigerTrade.Chart.Indicators.Custom")]
    [Indicator("X_TigerIndicatorProbe", "AAAA Indicator Probe", true, Type = typeof(TigerIndicatorProbe))]
    internal sealed class TigerIndicatorProbe : IndicatorBase
    {
        [Browsable(false)]
        public override bool ShowIndicatorValues
        {
            get { return false; }
        }

        [Browsable(false)]
        public override bool ShowIndicatorLabels
        {
            get { return false; }
        }

        [Browsable(false)]
        public override IndicatorCalculation Calculation
        {
            get { return IndicatorCalculation.OnEachTick; }
        }

        public TigerIndicatorProbe()
        {
            ShowIndicatorTitle = true;
        }

        protected override void Execute()
        {
        }

        public override void Render(DxVisualQueue visual)
        {
        }
    }
}
