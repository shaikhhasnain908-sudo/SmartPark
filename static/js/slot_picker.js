/* Interactive Parking Slot Picker & Fee Estimator */

document.addEventListener('DOMContentLoaded', () => {
  initSlotSelection();
});

function initSlotSelection() {
  const slotBoxes = document.querySelectorAll('.slot-box.free');
  const selectedSlotInput = document.getElementById('selected_slot_id');
  const selectedSlotNumberDisplay = document.getElementById('selected_slot_number');
  const durationInput = document.getElementById('duration');
  const hourlyRateInput = document.getElementById('hourly_rate');
  const estimatedFeeDisplay = document.getElementById('estimated_fee');
  const confirmBtn = document.getElementById('confirm_booking_btn');

  if (!slotBoxes.length) return;

  slotBoxes.forEach(box => {
    box.addEventListener('click', () => {
      // Clear previous selection
      slotBoxes.forEach(b => b.classList.remove('selected'));

      // Mark current selected
      box.classList.add('selected');
      const slotId = box.getAttribute('data-slot-id');
      const slotNum = box.getAttribute('data-slot-number');

      if (selectedSlotInput) selectedSlotInput.value = slotId;
      if (selectedSlotNumberDisplay) selectedSlotNumberDisplay.innerText = slotNum;
      if (confirmBtn) confirmBtn.disabled = false;

      updateFeeCalculation();
    });
  });

  if (durationInput) {
    durationInput.addEventListener('input', updateFeeCalculation);
    durationInput.addEventListener('change', updateFeeCalculation);
  }

  function updateFeeCalculation() {
    if (!durationInput || !hourlyRateInput || !estimatedFeeDisplay) return;

    const hrs = parseFloat(durationInput.value) || 1.0;
    const rate = parseFloat(hourlyRateInput.value) || 20.0;
    const total = (hrs * rate).toFixed(2);

    estimatedFeeDisplay.innerText = `₹${total}`;
  }
}
